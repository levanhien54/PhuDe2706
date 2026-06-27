import logging
import os
import sys
import tempfile
import time
import traceback

import torch
from fastapi import FastAPI, UploadFile, File, HTTPException
import whisperx

# ---------------------------------------------------------------------------
# Logging — verbose, stdout, timestamped, so `docker compose logs whisperx`
# shows every step and full tracebacks for diagnosing deployment errors.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [whisperx] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("whisperx")

app = FastAPI(title="WhisperX API")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"
MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "").strip() or None

_model = None
_align_cache = {}
_diarize_model = None


@app.on_event("startup")
def _log_startup():
    log.info("startup begin")
    log.info("torch=%s cuda_available=%s device=%s compute_type=%s",
             torch.__version__, torch.cuda.is_available(), DEVICE, COMPUTE_TYPE)
    if DEVICE == "cuda":
        try:
            log.info("gpu=%s vram_total=%.1fGB",
                     torch.cuda.get_device_name(0),
                     torch.cuda.get_device_properties(0).total_memory / 1e9)
        except Exception as e:
            log.warning("could not query GPU props: %s", e)
    else:
        log.warning("CUDA not available — running on CPU (will be very slow)")
    log.info("model=%s language=%s diarization=%s",
             MODEL_NAME, LANGUAGE or "auto", "on" if HF_TOKEN else "off (no HF_TOKEN)")
    log.info("startup done — model loads lazily on first /transcribe")


def get_model():
    global _model
    if _model is None:
        t0 = time.monotonic()
        log.info("loading whisper model '%s' on %s ...", MODEL_NAME, DEVICE)
        _model = whisperx.load_model(MODEL_NAME, DEVICE, compute_type=COMPUTE_TYPE)
        log.info("whisper model loaded in %.1fs", time.monotonic() - t0)
    return _model


def get_align_model(language_code):
    if language_code not in _align_cache:
        t0 = time.monotonic()
        log.info("loading alignment model for language '%s' ...", language_code)
        model_a, metadata = whisperx.load_align_model(language_code=language_code, device=DEVICE)
        _align_cache[language_code] = (model_a, metadata)
        log.info("alignment model '%s' loaded in %.1fs", language_code, time.monotonic() - t0)
    return _align_cache[language_code]


def get_diarize_model():
    global _diarize_model
    if _diarize_model is None and HF_TOKEN:
        t0 = time.monotonic()
        log.info("loading diarization pipeline ...")
        _diarize_model = whisperx.DiarizationPipeline(use_auth_token=HF_TOKEN, device=DEVICE)
        log.info("diarization pipeline loaded in %.1fs", time.monotonic() - t0)
    return _diarize_model


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": DEVICE,
        "model": MODEL_NAME,
        "model_loaded": _model is not None,
        "diarization": bool(HF_TOKEN),
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    req_start = time.monotonic()
    log.info("transcribe request: filename=%s", file.filename)
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        data = await file.read()
        tmp.write(data)
        tmp.flush()
        tmp.close()
        log.info("received %.2f MB -> %s", len(data) / 1e6, tmp.name)

        audio = whisperx.load_audio(tmp.name)
        log.info("audio loaded: %.1fs of samples", len(audio) / 16000.0)

        model = get_model()
        t0 = time.monotonic()
        result = model.transcribe(audio, language=LANGUAGE, batch_size=16)
        lang = result.get("language", "en")
        log.info("transcribe done in %.1fs: language=%s raw_segments=%d",
                 time.monotonic() - t0, lang, len(result.get("segments", [])))

        # word-level alignment (optional — fall back to coarse segments on failure)
        try:
            model_a, metadata = get_align_model(lang)
            t0 = time.monotonic()
            result = whisperx.align(result["segments"], model_a, metadata, audio, DEVICE,
                                    return_char_alignments=False)
            log.info("alignment done in %.1fs", time.monotonic() - t0)
        except Exception:
            log.warning("alignment failed, using coarse segments:\n%s", traceback.format_exc())

        # optional diarization
        diarize = get_diarize_model()
        if diarize is not None:
            try:
                t0 = time.monotonic()
                diarize_segments = diarize(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
                log.info("diarization done in %.1fs", time.monotonic() - t0)
            except Exception:
                log.warning("diarization failed, segments will have speaker=null:\n%s",
                            traceback.format_exc())

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
        log.info("transcribe request complete: %d segments in %.1fs total",
                 len(segments), time.monotonic() - req_start)
        return {"segments": segments}
    except Exception as e:
        log.error("transcription failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}")
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)
