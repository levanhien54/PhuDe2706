import os
import sys
import logging
import asyncio
import threading
import time
import traceback
import torch
import soundfile as sf
import numpy as np

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [omnivoice] %(message)s")
log = logging.getLogger("omnivoice")

app = FastAPI(title="OmniVoice TTS Adapter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    language: str = "vi"
    output_path: str
    reference_audio: str | None = None
    target_duration: float | None = None  # seconds; ask the model to render ~this long
    ref_text: str | None = None           # transcript of reference_audio (skips ASR auto-transcribe)

# --- Replica pool ---------------------------------------------------------
# A single CUDA model instance is NOT safe to call from multiple threads at once
# (concurrent generate() on one model corrupts output / crashes CUDA). To get real
# parallelism on a 23GB GPU we load N *independent* replicas and hand each in-flight
# request its own exclusive replica via a thread-safe free-list. With STT/LLM unloaded
# during phase-2 there is ample VRAM for 2-3 replicas (~3GB each).
_NUM_REPLICAS = max(1, int(os.environ.get("OMNIVOICE_REPLICAS", "2")))
# Quality knobs (OmniVoiceGenerationConfig). num_step is the main quality lever: higher = more
# natural pronunciation at the cost of speed. OmniVoice runs ~40x realtime, so 64 (2x the model's
# default 32) is still fast. guidance_scale ~2.0-2.5; denoise + postprocess_output stay on (defaults).
_NUM_STEP = max(1, int(os.environ.get("OMNIVOICE_NUM_STEP", "64")))
_GUIDANCE = float(os.environ.get("OMNIVOICE_GUIDANCE", "2.0"))
_GEN_KWARGS = {"num_step": _NUM_STEP, "guidance_scale": _GUIDANCE}
log.info("OmniVoice generation config: num_step=%d guidance_scale=%.2f", _NUM_STEP, _GUIDANCE)
_replicas: list = []
_free_idxs: list = []     # indices of replicas currently available
_inflight = 0             # replicas currently executing generate()
_unloading = False
# One condition guards the whole pool (replica list, free-list, in-flight count, unload flag).
# A synth is a "reader" that grabs a free replica; /unload is a "writer" that flips _unloading
# and waits for in-flight generations to drain BEFORE freeing — so it never tears the pool out
# from under a running generate() (which would leak that replica's VRAM and corrupt the free-list).
_pool_cond = threading.Condition()


def _ensure_pool_locked():
    """Load the replica pool if empty. Caller MUST hold _pool_cond."""
    global _replicas, _free_idxs
    if _replicas:
        return
    from omnivoice import OmniVoice
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    source = _resolve_model_source()
    reps = []
    for i in range(_NUM_REPLICAS):
        try:
            t0 = time.monotonic()
            m = OmniVoice.from_pretrained(source, device_map=device, dtype=dtype)
            reps.append(m)
            log.info("OmniVoice replica %d/%d loaded in %.1fs on %s",
                     i + 1, _NUM_REPLICAS, time.monotonic() - t0, device)
        except Exception as e:
            # Degrade gracefully: run with however many replicas fit (never worse than 1).
            log.error("replica_load_failed idx=%d: %s\n%s", i, e, traceback.format_exc())
            break
    if not reps:
        raise RuntimeError("Failed to load any OmniVoice replica")
    _replicas = reps
    _free_idxs = list(range(len(reps)))
    log.info("OmniVoice pool ready: %d replica(s)", len(_replicas))


def _acquire_replica() -> int:
    """Block until a replica is free, mark it in-flight, and return its index."""
    global _inflight
    with _pool_cond:
        while True:
            if _unloading:
                _pool_cond.wait()
                continue
            _ensure_pool_locked()
            if _free_idxs:
                idx = _free_idxs.pop()
                _inflight += 1
                return idx
            _pool_cond.wait()


def _release_replica(idx: int) -> None:
    global _inflight
    with _pool_cond:
        _free_idxs.append(idx)
        _inflight -= 1
        _pool_cond.notify_all()

def _resolve_model_source() -> str:
    """Return local path if OMNIVOICE_MODEL_DIR exists and has files, else HF repo id."""
    local = os.environ.get("OMNIVOICE_MODEL_DIR", "").strip()
    if not local:
        # default relative to this service file
        local = os.path.join(os.path.dirname(__file__), "..", "models", "omnivoice")
    local = os.path.normpath(os.path.abspath(local))
    if os.path.isdir(local) and any(os.scandir(local)):
        log.info("Using local OmniVoice model: %s", local)
        return local
    log.info("Local OmniVoice model not found at %s — downloading from HuggingFace", local)
    return "k2-fsa/OmniVoice"

@app.on_event("startup")
def startup_event():
    # Lazy by default: replicas load on first /v1/audio/speech, AFTER the orchestrator
    # has unloaded STT/LLM for phase-2 — so they never compete with phase-1 for VRAM.
    if os.environ.get("OMNIVOICE_PRELOAD", "0").strip() == "1":
        log.info("OMNIVOICE_PRELOAD=1 — loading replica pool at startup")
        try:
            with _pool_cond:
                _ensure_pool_locked()
        except Exception as e:
            log.error(f"startup preload failed: {e}")
    else:
        log.info("OmniVoice ready (lazy load) — OMNIVOICE_REPLICAS=%d, loads on first request",
                 _NUM_REPLICAS)

def _synthesize_omnivoice(text, language, reference_audio, output_path, target_duration=None, ref_text=None):
    t0 = time.monotonic()

    # Native duration control: ask OmniVoice to render ~this many seconds, instead of
    # generating at its own pace and DSP-stretching afterward (better voice quality, and it
    # actually fits the original video/background-audio slot). A light corrective stretch in
    # the orchestrator still snaps it to the exact length.
    dur = target_duration if (target_duration and target_duration > 0) else None
    audio_tensor = None
    # Grab an exclusive replica; this blocks while /unload is draining and bumps the in-flight
    # count so unload cannot free the pool while this generate() is running.
    idx = _acquire_replica()
    model = _replicas[idx]
    try:
        if reference_audio and os.path.exists(reference_audio):
            try:
                audio_tensor = model.generate(text, ref_audio=reference_audio, ref_text=ref_text, language=language, duration=dur, **_GEN_KWARGS)
            except ValueError as e:
                if "Reference audio is empty" in str(e):
                    log.warning(f"Silence removal failed for {reference_audio}, retrying with preprocess_prompt=False")
                    try:
                        audio_tensor = model.generate(text, ref_audio=reference_audio, ref_text=ref_text, language=language, preprocess_prompt=False, duration=dur, **_GEN_KWARGS)
                    except Exception as inner_e:
                        log.error(f"Failed again with preprocess_prompt=False: {inner_e}. Falling back to non-cloned voice.")
                else:
                    log.error(f"ValueError during generation: {e}. Falling back to non-cloned voice.")
            except Exception as e:
                log.error(f"Error during voice cloning generation: {e}. Falling back to non-cloned voice.")

        if audio_tensor is None:
            log.info("Generating without reference audio (fallback or no ref provided)")
            audio_tensor = model.generate(text, language=language, duration=dur, **_GEN_KWARGS)
    except Exception:
        # On a failed generation (e.g. CUDA OOM) free the cache so a fragmented/wedged context
        # isn't handed straight to the next request and cascade into more failures.
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        raise
    finally:
        _release_replica(idx)
        
    # Use the model's real sample rate (set at load to feature_extractor.sampling_rate),
    # not a hard-coded guess — a non-24kHz build would otherwise get a wrong WAV header and
    # the whole segment would play at the wrong speed/pitch.
    sr = getattr(model, "sampling_rate", None) or 24000

    if isinstance(audio_tensor, list):
        audio_data = audio_tensor[0]
    elif isinstance(audio_tensor, tuple):
        if isinstance(audio_tensor[0], int):
            sr = audio_tensor[0]
            audio_data = audio_tensor[1]
        else:
            audio_data = audio_tensor[0]
    else:
        audio_data = audio_tensor
        
    if hasattr(audio_data, 'cpu'):
        audio_data = audio_data.cpu().numpy()
    elif isinstance(audio_data, list):
        audio_data = np.array(audio_data)
        
    abs_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)
    
    if len(audio_data.shape) > 1 and audio_data.shape[0] < audio_data.shape[1]:
        audio_data = audio_data.T
        
    sf.write(abs_output, audio_data, sr)
    log.info("omnivoice done in %.1fs -> %s", time.monotonic() - t0, abs_output)

@app.get("/health")
def health():
    # Lazy pool: report readiness without forcing a load (200 even before first request).
    with _pool_cond:
        n = len(_replicas)
    return {"status": "ok", "model_loaded": n > 0, "replicas": n}


@app.post("/unload")
def unload():
    """Free all replicas so phase-1 (STT/LLM) can reclaim VRAM between jobs.
    Waits for any in-flight generate() to finish first so VRAM is actually released."""
    global _replicas, _free_idxs, _unloading
    with _pool_cond:
        _unloading = True
        _pool_cond.notify_all()        # nudge waiters to re-check the flag
        while _inflight > 0:
            _pool_cond.wait()
        _replicas = []
        _free_idxs = []
        _unloading = False
        _pool_cond.notify_all()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    log.info("OmniVoice replicas unloaded, CUDA cache cleared.")
    return {"status": "unloaded"}


@app.post("/v1/audio/speech")
async def synthesize(req: TTSRequest):
    log.info(f"tts request: chars={len(req.text)} lang={req.language} ref={req.reference_audio}")
    try:
        await asyncio.to_thread(
            _synthesize_omnivoice,
            req.text, req.language, req.reference_audio, req.output_path, req.target_duration, req.ref_text
        )
    except Exception as e:
        log.error(f"tts failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
        
    if not os.path.exists(req.output_path):
        raise HTTPException(status_code=500, detail="tts produced no output")
        
    return {"output_path": req.output_path}
