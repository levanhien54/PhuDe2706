import asyncio
import logging
import os
import sys
import time
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

GPT_SOVITS_DIR = os.environ.get("GPT_SOVITS_DIR", "/app/GPT-SoVITS")
DEFAULT_PROMPT_TEXT = os.environ.get("GPT_SOVITS_PROMPT_TEXT", "")
DEFAULT_PROMPT_LANG = os.environ.get("GPT_SOVITS_PROMPT_LANG", "auto")

if os.path.isdir(GPT_SOVITS_DIR):
    os.chdir(GPT_SOVITS_DIR)

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
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:
        log.warning("tts_unload_failed: %s", e)
    return {"status": "unloaded"}


async def _synthesize_edge_tts_async(text: str, lang: str, output_path: str):
    """Use Microsoft edge-tts (online, free) for synthesis."""
    import edge_tts
    import subprocess

    voice = EDGE_TTS_VOICES.get(lang[:2], EDGE_TTS_VOICES["vi"])
    log.info("edge-tts: voice=%s chars=%d", voice, len(text))
    t0 = time.monotonic()

    abs_output = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_output)
    os.makedirs(out_dir, exist_ok=True)
    tmp_mp3 = os.path.join(out_dir, os.path.basename(abs_output).replace(".wav", "_tts_tmp.mp3"))
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(tmp_mp3)
    result = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "24000", "-ac", "1", abs_output],
        capture_output=True, text=True,
    )
    if os.path.exists(tmp_mp3):
        os.remove(tmp_mp3)
    if result.returncode != 0 or not os.path.exists(abs_output):
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[:300]}")

    log.info("edge-tts done in %.1fs -> %s", time.monotonic() - t0, output_path)


_tts_instance = None
_tts_config = None

def _get_gpt_sovits_instance():
    global _tts_instance, _tts_config
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
