import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="GPT-SoVITS Adapter API")

GPT_SOVITS_DIR = os.environ.get("GPT_SOVITS_DIR", "/app/GPT-SoVITS")
# Default reference prompt transcription (used when caller omits prompt_text).
DEFAULT_PROMPT_TEXT = os.environ.get("GPT_SOVITS_PROMPT_TEXT", "")
DEFAULT_PROMPT_LANG = os.environ.get("GPT_SOVITS_PROMPT_LANG", "auto")


class TTSRequest(BaseModel):
    text: str
    text_language: str = "vi"
    refer_wav_path: str
    output_path: str
    prompt_text: str | None = None
    prompt_language: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


def synthesize_wav(text, text_language, refer_wav_path, output_path, prompt_text, prompt_language):
    """
    Run GPT-SoVITS inference and write a WAV to output_path.

    GPT-SoVITS exposes inference via GPT_SoVITS/inference_webui.py's get_tts_wav generator.
    The exact import path depends on the repo revision pinned in the Dockerfile.
    This adapter calls into it; adjust the import if you pin a different revision.

    TODO: If the pinned revision changes the module layout, update the import below.
    Integration point: `from GPT_SoVITS.inference_webui import get_tts_wav`
    """
    import sys
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


@app.post("/tts")
def tts(req: TTSRequest):
    if not os.path.exists(req.refer_wav_path):
        raise HTTPException(status_code=400, detail=f"reference audio not found: {req.refer_wav_path}")
    try:
        synthesize_wav(
            req.text, req.text_language, req.refer_wav_path,
            req.output_path, req.prompt_text, req.prompt_language,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"tts failed: {e}")
    if not os.path.exists(req.output_path):
        raise HTTPException(status_code=500, detail="tts produced no output file")
    return {"output_path": req.output_path}
