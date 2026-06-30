import ctypes
import logging
import os
import sys
import tempfile
import threading
import time
import traceback

# ---------------------------------------------------------------------------
# CUDA 12 DLL bootstrap — must run BEFORE torch/ctranslate2 import.
# PyTorch cu118 bundles cudnn64_9.dll (which needs CUDA 12 runtime).
# ctranslate2 4.x also needs cublas64_12.dll.
# We preload them via ctypes so Windows' LoadLibrary reuses the handles.
# ---------------------------------------------------------------------------
def _preload_cuda12_dlls():
    _CUDA12_PATHS = [
        # Ollama bundles cudart64_12.dll + cublas DLLs for its GPU backend
        r"C:\Users\ezycloudx-admin\AppData\Local\Programs\Ollama\lib\ollama\cuda_v12\cudart64_12.dll",
        r"C:\Users\ezycloudx-admin\AppData\Local\Programs\Ollama\lib\ollama\cuda_v12\cublas64_12.dll",
        r"C:\Users\ezycloudx-admin\AppData\Local\Programs\Ollama\lib\ollama\cuda_v12\cublasLt64_12.dll",
    ]
    # Also scan venv/nvidia/* for cuBLAS and nvrtc
    nvidia_root = os.path.join(os.path.dirname(__file__), "..", "venv", "lib", "site-packages", "nvidia")
    nvidia_root = os.path.normpath(nvidia_root)
    if os.path.isdir(nvidia_root):
        for root, _dirs, files in os.walk(nvidia_root):
            for f in files:
                if f.endswith(".dll") and any(k in f for k in ("cublas", "nvrtc")):
                    _CUDA12_PATHS.append(os.path.join(root, f))

    loaded = []
    for path in _CUDA12_PATHS:
        if os.path.exists(path):
            try:
                ctypes.WinDLL(path)
                loaded.append(os.path.basename(path))
            except OSError:
                pass
    return loaded

_preloaded = _preload_cuda12_dlls()

# whisperx.load_audio shells out to a bare "ffmpeg" resolved via PATH. Ensure the bundled
# FFmpeg is discoverable even when the service is launched without PATH set up (e.g. Electron).
def _ensure_ffmpeg_on_path():
    import shutil
    if shutil.which("ffmpeg"):
        return
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in (
        os.path.join(project_root, "ffmpeg_extracted", "ffmpeg-master-latest-win64-gpl", "bin"),
        project_root,
    ):
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            break

_ensure_ffmpeg_on_path()

import torch
# PyTorch cu118's bundled cudnn64_9.dll is a stub missing cudnnGetLibConfig.
# Disable cuDNN so pyannote/torch ops fall back to basic CUDA kernels.
torch.backends.cudnn.enabled = False

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _detect_device():
    env_device = os.environ.get("DEVICE", "").strip().lower()
    if env_device in ("cpu", "cuda"):
        return env_device
    if not torch.cuda.is_available():
        return "cpu"
    # Check ctranslate2 can use CUDA — requires cublas64_12.dll (preloaded above)
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cuda")
        return "cuda" if supported else "cpu"
    except Exception:
        return "cpu"

DEVICE = _detect_device()
COMPUTE_TYPE = os.environ.get("COMPUTE_TYPE", "float16" if DEVICE == "cuda" else "int8")
MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")
BATCH_SIZE = int(os.environ.get("WHISPER_BATCH_SIZE", "32"))  # 23GB GPU handles >16
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "").strip() or None   # explicit download root
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "").strip() or None
PRELOAD = os.environ.get("WHISPER_PRELOAD", "0").strip() == "1"

_model = None
_align_cache = {}
_diarize_model = None
# Serialize lazy model/cache initialization so two concurrent first-requests can't both
# load (double VRAM, one instance leaked) or race on the _align_cache dict.
_load_lock = threading.Lock()


@app.on_event("startup")
async def _preload_on_startup():
    if PRELOAD:
        import asyncio
        await asyncio.to_thread(get_model)

@app.on_event("startup")
def _log_startup():
    log.info("startup begin")
    log.info("cuda12_dlls_preloaded=%s", _preloaded)
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
    if MODEL_DIR:
        log.info("model_dir=%s", MODEL_DIR)
    if PRELOAD:
        log.info("WHISPER_PRELOAD=1 — loading model now at startup")
    else:
        log.info("startup done — model loads lazily on first /transcribe")


def get_model():
    global _model
    with _load_lock:
        if _model is None:
            t0 = time.monotonic()
            log.info("loading whisper model '%s' on %s ...", MODEL_NAME, DEVICE)
            kwargs = {"compute_type": COMPUTE_TYPE}
            if MODEL_DIR:
                kwargs["download_root"] = MODEL_DIR
            _model = whisperx.load_model(MODEL_NAME, DEVICE, **kwargs)
            log.info("whisper model loaded in %.1fs", time.monotonic() - t0)
    return _model


def get_align_model(language_code):
    with _load_lock:
        if language_code not in _align_cache:
            t0 = time.monotonic()
            log.info("loading alignment model for language '%s' ...", language_code)
            model_a, metadata = whisperx.load_align_model(language_code=language_code, device=DEVICE)
            _align_cache[language_code] = (model_a, metadata)
            log.info("alignment model '%s' loaded in %.1fs", language_code, time.monotonic() - t0)
    return _align_cache[language_code]


def get_diarize_model():
    global _diarize_model
    with _load_lock:
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

@app.post("/unload")
def unload():
    global _model, _align_cache, _diarize_model
    _model = None
    _align_cache.clear()
    _diarize_model = None
    
    if DEVICE == "cuda":
        import torch
        torch.cuda.empty_cache()
        log.info("Models unloaded and CUDA cache cleared.")
        
    return {"status": "unloaded"}


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
        result = model.transcribe(audio, language=LANGUAGE, batch_size=BATCH_SIZE)
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
