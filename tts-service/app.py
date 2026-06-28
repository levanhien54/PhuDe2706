import logging
import os
import sys
import time
import traceback

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging — verbose, stdout, timestamped, so `docker compose logs tts` shows
# every step and full tracebacks for diagnosing deployment errors.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [tts] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tts")

app = FastAPI(title="GPT-SoVITS Adapter API")

GPT_SOVITS_DIR = os.environ.get("GPT_SOVITS_DIR", "/app/GPT-SoVITS")
# Default reference prompt transcription (used when caller omits prompt_text).
DEFAULT_PROMPT_TEXT = os.environ.get("GPT_SOVITS_PROMPT_TEXT", "")
DEFAULT_PROMPT_LANG = os.environ.get("GPT_SOVITS_PROMPT_LANG", "auto")

_import_ok = None  # cache of the get_tts_wav import probe


class TTSRequest(BaseModel):
    text: str
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
        else:
            log.warning("CUDA not available — GPT-SoVITS will be very slow on CPU")
    except Exception as e:
        log.warning("could not import torch at startup: %s", e)
    log.info("GPT_SOVITS_DIR=%s exists=%s", GPT_SOVITS_DIR, os.path.isdir(GPT_SOVITS_DIR))
    log.info("default_prompt_lang=%s default_prompt_text=%r",
             DEFAULT_PROMPT_LANG, DEFAULT_PROMPT_TEXT)
    # Probe the integration import once so failures surface at boot in the logs,
    # not only on the first /tts request.
    _probe_import()
    log.info("startup done")


def _probe_import():
    global _import_ok
    if GPT_SOVITS_DIR not in sys.path:
        sys.path.insert(0, GPT_SOVITS_DIR)
    try:
        from GPT_SoVITS.inference_webui import get_tts_wav  # noqa: F401  # type: ignore
        _import_ok = True
        log.info("integration import OK: GPT_SoVITS.inference_webui.get_tts_wav")
    except Exception:
        _import_ok = False
        log.warning(
            "integration import FAILED (get_tts_wav). /health stays up; /tts will 500 "
            "until this is fixed. This is the single integration point — adjust the "
            "import in synthesize_wav() to match the pinned GPT-SoVITS revision.\n%s",
            traceback.format_exc(),
        )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gpt_sovits_dir": GPT_SOVITS_DIR,
        "dir_exists": os.path.isdir(GPT_SOVITS_DIR),
        "integration_import_ok": _import_ok,
    }

@app.post("/unload")
def unload():
    try:
        import sys, gc
        mod = sys.modules.get("GPT_SoVITS.inference_webui")
        if mod is not None:
            for _name in ("vq_model", "t2s_model", "bert_model", "ssl_model", "hps"):
                try:
                    setattr(mod, _name, None)
                except Exception:
                    pass
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            log.info("TTS models unloaded and CUDA cache cleared.")
    except Exception as e:
        log.warning("tts_unload_failed: %s", e)
    return {"status": "unloaded"}


def synthesize_wav(text, text_language, refer_wav_path, output_path, prompt_text, prompt_language):
    """
    Run GPT-SoVITS inference and write a WAV to output_path.

    GPT-SoVITS exposes inference via GPT_SoVITS/inference_webui.py's get_tts_wav generator.
    The exact import path depends on the repo revision pinned in the Dockerfile.

    Integration point: `from GPT_SoVITS.inference_webui import get_tts_wav`
    If the pinned revision changes the module layout, update the import below.
    """
    if GPT_SOVITS_DIR not in sys.path:
        sys.path.insert(0, GPT_SOVITS_DIR)

    # Lazy import so the service can boot /health even before models are present.
    try:
        from GPT_SoVITS.inference_webui import get_tts_wav  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"Could not import get_tts_wav from GPT_SoVITS.inference_webui. "
            f"Check that GPT_SOVITS_DIR={GPT_SOVITS_DIR} is correct and the repo "
            f"is fully cloned. Original error: {exc}"
        ) from exc

    import soundfile as sf
    import numpy as np

    pt = prompt_text if prompt_text is not None else DEFAULT_PROMPT_TEXT
    pl = prompt_language if prompt_language is not None else DEFAULT_PROMPT_LANG
    log.info("synthesize: lang=%s chars=%d ref=%s prompt_lang=%s",
             text_language, len(text), refer_wav_path, pl)

    t0 = time.monotonic()
    sr = None
    chunks = []
    for sr_out, chunk in get_tts_wav(
        ref_wav_path=refer_wav_path,
        prompt_text=pt,
        prompt_language=pl,
        text=text,
        text_language=text_language,
    ):
        sr = sr_out
        chunks.append(chunk)

    if not chunks:
        raise RuntimeError("GPT-SoVITS returned no audio")

    audio = np.concatenate(chunks)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    sf.write(output_path, audio, sr)
    log.info("synthesize done in %.1fs: sr=%s samples=%d -> %s",
             time.monotonic() - t0, sr, len(audio), output_path)


@app.post("/tts")
def tts(req: TTSRequest):
    log.info("tts request: chars=%d lang=%s out=%s", len(req.text), req.text_language, req.output_path)
    if not os.path.exists(req.refer_wav_path):
        log.error("reference audio not found: %s", req.refer_wav_path)
        raise HTTPException(status_code=400, detail=f"reference audio not found: {req.refer_wav_path}")
    try:
        synthesize_wav(
            req.text, req.text_language, req.refer_wav_path,
            req.output_path, req.prompt_text, req.prompt_language,
        )
    except Exception as e:
        log.error("tts failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"tts failed: {e}")
    if not os.path.exists(req.output_path):
        log.error("tts produced no output file at %s", req.output_path)
        raise HTTPException(status_code=500, detail="tts produced no output file")
    return {"output_path": req.output_path}
