import os
import tempfile
import torch
from fastapi import FastAPI, UploadFile, File, HTTPException
import whisperx

app = FastAPI(title="WhisperX API")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"
MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "").strip() or None

_model = None
_align_cache = {}
_diarize_model = None


def get_model():
    global _model
    if _model is None:
        _model = whisperx.load_model(MODEL_NAME, DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def get_align_model(language_code):
    if language_code not in _align_cache:
        model_a, metadata = whisperx.load_align_model(language_code=language_code, device=DEVICE)
        _align_cache[language_code] = (model_a, metadata)
    return _align_cache[language_code]


def get_diarize_model():
    global _diarize_model
    if _diarize_model is None and HF_TOKEN:
        _diarize_model = whisperx.DiarizationPipeline(use_auth_token=HF_TOKEN, device=DEVICE)
    return _diarize_model


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "model": MODEL_NAME}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp.close()

        audio = whisperx.load_audio(tmp.name)
        model = get_model()
        result = model.transcribe(audio, language=LANGUAGE, batch_size=16)
        lang = result.get("language", "en")

        # word-level alignment
        try:
            model_a, metadata = get_align_model(lang)
            result = whisperx.align(result["segments"], model_a, metadata, audio, DEVICE, return_char_alignments=False)
        except Exception:
            pass  # alignment optional; fall back to coarse segments

        # optional diarization
        diarize = get_diarize_model()
        if diarize is not None:
            try:
                diarize_segments = diarize(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception:
                pass

        segments = []
        for s in result.get("segments", []):
            text = (s.get("text") or "").strip()
            if not text:
                continue
            segments.append({
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": text,
                "speaker": s.get("speaker"),
            })
        return {"segments": segments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}")
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)
