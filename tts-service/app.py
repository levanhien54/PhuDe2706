import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [tts] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tts")

app = FastAPI(title="TTS Adapter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # no cookie auth; wildcard-origin + credentials is unsafe
    allow_methods=["*"],
    allow_headers=["*"],
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Default to a project-relative dir (the old "/app/..." default only existed inside the Docker
# image and never resolves on the Windows deployment target).
GPT_SOVITS_DIR = os.environ.get("GPT_SOVITS_DIR", os.path.join(_PROJECT_ROOT, "GPT-SoVITS"))
DEFAULT_PROMPT_TEXT = os.environ.get("GPT_SOVITS_PROMPT_TEXT", "")
DEFAULT_PROMPT_LANG = os.environ.get("GPT_SOVITS_PROMPT_LANG", "auto")
# edge-tts is an ONLINE Microsoft service — disabled by default in this offline product.
# Set TTS_ALLOW_ONLINE_FALLBACK=1 to explicitly permit it as a last-resort fallback.
ALLOW_ONLINE_FALLBACK = os.environ.get("TTS_ALLOW_ONLINE_FALLBACK", "0").strip() == "1"

if os.path.isdir(GPT_SOVITS_DIR):
    os.chdir(GPT_SOVITS_DIR)


# GPT-SoVITS is not safe to init or run concurrently on a single GPU: two overlapping first
# requests could double-init (leaking one instance's VRAM), and tts.run() drives a
# non-reentrant CUDA model. _load_lock serializes lazy init; _infer_lock serializes generation.
_load_lock = threading.Lock()
_infer_lock = threading.Lock()


def _ensure_ffmpeg_on_path():
    """edge-tts output is transcoded via a bare "ffmpeg" resolved on PATH. Make the bundled
    FFmpeg discoverable even when launched without PATH set up (e.g. Electron)."""
    import shutil
    if shutil.which("ffmpeg"):
        return
    for d in (
        os.path.join(_PROJECT_ROOT, "ffmpeg_extracted", "ffmpeg-master-latest-win64-gpl", "bin"),
        _PROJECT_ROOT,
    ):
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            break


_ensure_ffmpeg_on_path()

# edge-tts voice map by language code
EDGE_TTS_VOICES = {
    "vi": "vi-VN-HoaiMyNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
}

_gpt_sovits_ok = None  # None=unknown, True=available, False=unavailable


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    text_language: str = "vi"
    refer_wav_path: str
    output_path: str
    prompt_text: str | None = None
    prompt_language: str | None = None


@app.on_event("startup")
def _log_startup():
    log.info("startup begin")
    try:
        import torch
        log.info("torch=%s cuda_available=%s", torch.__version__, torch.cuda.is_available())
        if torch.cuda.is_available():
            log.info("gpu=%s", torch.cuda.get_device_name(0))
    except Exception as e:
        log.warning("could not import torch: %s", e)

    log.info("GPT_SOVITS_DIR=%s exists=%s", GPT_SOVITS_DIR, os.path.isdir(GPT_SOVITS_DIR))
    _probe_gpt_sovits()

    try:
        import edge_tts
        log.info("edge-tts available: %s", edge_tts.__version__)
    except ImportError:
        log.warning("edge-tts not installed — pip install edge-tts")

    log.info("startup done")


def _probe_gpt_sovits():
    global _gpt_sovits_ok
    _add_sovits_paths()
    try:
        from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: F401
        _gpt_sovits_ok = True
        log.info("GPT-SoVITS TTS_infer_pack: available")
    except Exception:
        _gpt_sovits_ok = False
        log.warning("GPT-SoVITS unavailable (will use edge-tts):\n%s", traceback.format_exc())


def _add_sovits_paths():
    for p in [GPT_SOVITS_DIR, os.path.join(GPT_SOVITS_DIR, "GPT_SoVITS")]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gpt_sovits_dir": GPT_SOVITS_DIR,
        "dir_exists": os.path.isdir(GPT_SOVITS_DIR),
        "integration_import_ok": _gpt_sovits_ok,
        "engine": "gpt_sovits" if _gpt_sovits_ok else "edge_tts",
    }


@app.post("/unload")
def unload():
    global _tts_instance, _tts_config
    try:
        # Drain any in-flight generation, then actually drop the model references so the VRAM
        # can be collected — empty_cache() alone does nothing while the globals still hold it.
        with _infer_lock:
            _tts_instance = None
            _tts_config = None
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    except Exception as e:
        log.warning("tts_unload_failed: %s", e)
    return {"status": "unloaded"}


async def _synthesize_edge_tts_async(text: str, lang: str, output_path: str):
    """Use Microsoft edge-tts (ONLINE) for synthesis. Refuses to run unless explicitly
    enabled, so an offline deployment fails loudly instead of silently hitting the network."""
    if not ALLOW_ONLINE_FALLBACK:
        raise RuntimeError(
            "GPT-SoVITS unavailable and the edge-tts fallback is disabled. edge-tts is an "
            "online Microsoft service, but this is an offline product. Fix the GPT-SoVITS "
            f"installation (GPT_SOVITS_DIR={GPT_SOVITS_DIR}, exists={os.path.isdir(GPT_SOVITS_DIR)}) "
            "or set TTS_ALLOW_ONLINE_FALLBACK=1 to explicitly permit the online fallback."
        )
    import edge_tts
    import subprocess

    voice = EDGE_TTS_VOICES.get(lang[:2], EDGE_TTS_VOICES["vi"])
    log.info("edge-tts: voice=%s chars=%d", voice, len(text))
    t0 = time.monotonic()

    abs_output = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_output)
    os.makedirs(out_dir, exist_ok=True)
    # Unique tmp name via tempfile — str.replace(".wav", ...) collided for non-.wav outputs
    # and for concurrent requests writing the same basename.
    _base = os.path.splitext(os.path.basename(abs_output))[0]
    _fd, tmp_mp3 = tempfile.mkstemp(prefix=_base + "_tts_", suffix=".mp3", dir=out_dir)
    os.close(_fd)
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp_mp3)
        result = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "24000", "-ac", "1", abs_output],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.exists(abs_output):
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[:300]}")
    finally:
        # Always clean up the intermediate mp3 — even if ffmpeg is missing (FileNotFoundError)
        # or the conversion fails.
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except OSError:
                pass

    log.info("edge-tts done in %.1fs -> %s", time.monotonic() - t0, output_path)


_tts_instance = None
_tts_config = None

def _get_gpt_sovits_instance():
    global _tts_instance, _tts_config
    # Serialize lazy init so two concurrent first-requests can't both build a TTS instance
    # (double VRAM, one leaked). Double-checked under the lock.
    with _load_lock:
        if _tts_instance is not None:
            return _tts_instance

        _add_sovits_paths()
        from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

        cfg_path = os.path.join(GPT_SOVITS_DIR, "GPT_SoVITS", "configs", "tts_infer.yaml")
        _tts_config = TTS_Config(cfg_path)
        _tts_instance = TTS(_tts_config)
        log.info("GPT-SoVITS TTS instance created")
        return _tts_instance


def _synthesize_gpt_sovits(text, lang, refer_wav_path, output_path, prompt_text, prompt_language):
    import soundfile as sf
    import numpy as np

    tts = _get_gpt_sovits_instance()
    pt = prompt_text if prompt_text is not None else DEFAULT_PROMPT_TEXT
    pl = prompt_language if prompt_language is not None else DEFAULT_PROMPT_LANG
    log.info("gpt-sovits: lang=%s chars=%d ref=%s", lang, len(text), refer_wav_path)
    t0 = time.monotonic()

    inputs = {
        "text": text,
        "text_language": lang,
        "ref_audio_path": refer_wav_path,
        "prompt_text": pt,
        "prompt_language": pl,
        "top_k": 5,
        "top_p": 1.0,
        "temperature": 1.0,
        "speed_factor": 1.0,
    }
    sr = None
    chunks = []
    # The shared GPT-SoVITS CUDA model is not reentrant — only one generation may run at a time.
    with _infer_lock:
        for item in tts.run(inputs):
            sr = item[0]
            chunks.append(item[1])

    if not chunks:
        raise RuntimeError("GPT-SoVITS returned no audio")

    audio = np.concatenate(chunks)
    abs_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)
    sf.write(abs_output, audio, sr)
    log.info("gpt-sovits done in %.1fs -> %s", time.monotonic() - t0, abs_output)


async def synthesize_wav_async(text, text_language, refer_wav_path, output_path, prompt_text, prompt_language):
    if _gpt_sovits_ok:
        try:
            await asyncio.to_thread(
                _synthesize_gpt_sovits,
                text, text_language, refer_wav_path, output_path, prompt_text, prompt_language,
            )
            return
        except Exception as e:
            log.warning("gpt-sovits failed, falling back to edge-tts: %s", e)

    await _synthesize_edge_tts_async(text, text_language, output_path)


@app.post("/tts")
async def tts(req: TTSRequest):
    log.info("tts request: chars=%d lang=%s out=%s", len(req.text), req.text_language, req.output_path)
    if not os.path.exists(req.refer_wav_path):
        log.warning("reference audio not found: %s (will use edge-tts only)", req.refer_wav_path)
    try:
        await synthesize_wav_async(
            req.text, req.text_language, req.refer_wav_path,
            req.output_path, req.prompt_text, req.prompt_language,
        )
    except Exception:
        log.error("tts failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="tts failed")
    if not os.path.exists(req.output_path):
        raise HTTPException(status_code=500, detail="tts produced no output file")
    return {"output_path": req.output_path}
