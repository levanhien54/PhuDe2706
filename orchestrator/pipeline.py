import os
import asyncio
import time
import shutil
import httpx

from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager, get_vram_manager
from orchestrator.logger import get_logger, bind_job_context, clear_job_context
from orchestrator.stages import (
    run_audio_separate, run_transcribe, run_translate,
    run_synthesize, run_video_ocr, run_lip_sync,
)
from orchestrator.audio_sync import mix_audio_to_video
from orchestrator.database import get_job, update_job_status, get_app_config

def _save_progress(job_id: str, phase_name: str, current_results: dict):
    job_info = get_job(job_id) or {}
    full_results = job_info.get("results", {})
    full_results[phase_name] = {k: v.summary() for k, v in current_results.items()}
    update_job_status(job_id, job_info.get("status", "PROCESSING"), results=full_results)

log = get_logger(__name__)


# --- Cooperative job cancellation ---------------------------------------------
# A "Huy" request from the UI registers the job_id here; the pipeline checks it
# between stages (via _check_cancel) and raises JobCancelled, which the worker
# turns into a CANCELLED status. Combined with task.cancel() (in the worker) this
# also interrupts a stage that is mid-await on a service call.
class JobCancelled(Exception):
    """Raised inside the pipeline when the user cancels a running job."""


_cancel_requested: set[str] = set()


def request_cancel(job_id: str) -> None:
    _cancel_requested.add(job_id)


def is_cancel_requested(job_id: str) -> bool:
    return job_id in _cancel_requested


def clear_cancel(job_id: str) -> None:
    _cancel_requested.discard(job_id)


def _check_cancel(job_id: str) -> None:
    if job_id in _cancel_requested:
        log.info("job_cancel_detected", job_id=job_id)
        raise JobCancelled(job_id)


async def run_pipeline_phase1(job: PipelineJob, settings: Settings) -> tuple[dict[str, StageResult], list[SrtSegment]]:
    bind_job_context(job.job_id, job.filename)
    vram = get_vram_manager(settings)
    results: dict[str, StageResult] = {}
    
    log.info("pipeline_phase1_start", vram_profile=settings.vram_profile, target_lang=job.target_language)
    _check_cancel(job.job_id)

    # Reclaim VRAM held by TTS replicas from a previous job so STT/LLM run with full headroom.
    await free_tts_models(settings)

    # M2 + M7 run concurrently
    sep_task = asyncio.create_task(run_audio_separate(job, settings, vram))
    ocr_task = asyncio.create_task(run_video_ocr(job, settings, vram))
    sep_result, ocr_result = await asyncio.gather(sep_task, ocr_task)

    results["audio_separate"] = sep_result
    results["video_ocr"] = ocr_result
    _save_progress(job.job_id, "phase1", results)

    if not ocr_result.success:
        log.warning("video_ocr_failed_continuing", reason="OCR is optional, continuing pipeline")

    if not sep_result.success:
        log.error("pipeline_abort", reason="audio_separate failed")
        clear_job_context()
        return results, []

    _check_cancel(job.job_id)
    # M3: WhisperX STT
    transcribe_result, segments = await run_transcribe(job, settings, vram)
    results["transcribe"] = transcribe_result
    _save_progress(job.job_id, "phase1", results)

    if not transcribe_result.success or not segments:
        log.error("pipeline_abort", reason="transcribe failed or empty")
        clear_job_context()
        return results, []

    _check_cancel(job.job_id)
    # M4: LLM Translate
    translate_result, translated_segments = await run_translate(job, segments, settings, vram)
    results["translate"] = translate_result
    _save_progress(job.job_id, "phase1", results)

    if not translate_result.success:
        log.warning("translate_failed_using_original")
        translated_segments = segments  # fallback
        
    clear_job_context()
    return results, translated_segments

async def free_stt_llm_models(settings: Settings):
    """Unload WhisperX + Ollama. Called at phase-2 start to make room for TTS replicas."""
    log.info("free_stt_llm_vram", msg="Unloading WhisperX + LLM before TTS")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(f"{settings.whisperx_api}/unload")
        except Exception as e:
            log.warning("whisperx_unload_failed", error=str(e))

        # Unload Ollama (by sending keep_alive=0)
        if settings.llm_backend == "ollama":
            try:
                await client.post(
                    f"{settings.ollama_host}/api/generate",
                    json={"model": settings.llm_model, "keep_alive": 0}
                )
            except Exception as e:
                log.warning("ollama_unload_failed", error=str(e))


async def free_tts_models(settings: Settings):
    """Unload TTS replicas. Called at phase-1 start to make room for STT/LLM."""
    log.info("free_tts_vram", msg="Unloading TTS replicas before STT/LLM")
    # Target the active TTS engine's port (omnivoice 3900 vs gpt_sovits 9880).
    tts_url = settings.omnivoice_api if settings.tts_engine == "omnivoice" else settings.tts_api
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(f"{tts_url}/unload")
        except Exception as e:
            log.warning("tts_unload_failed", error=str(e))


async def unload_all_models(settings: Settings):
    log.info("triggering_gpu_unload", msg="Freeing VRAM for heavy tasks...")
    await free_stt_llm_models(settings)
    await free_tts_models(settings)

async def run_pipeline_phase2(job: PipelineJob, segments: list[SrtSegment], settings: Settings) -> dict[str, StageResult]:
    bind_job_context(job.job_id, job.filename)
    vram = get_vram_manager(settings)
    results: dict[str, StageResult] = {}
    
    log.info("pipeline_phase2_start", vram_profile=settings.vram_profile, lipsync=settings.enable_lipsync)
    _check_cancel(job.job_id)

    # Free STT/LLM VRAM so the TTS replica pool has room to load and run in parallel.
    await free_stt_llm_models(settings)

    _check_cancel(job.job_id)
    # M5: TTS Synthesize
    synth_result = await run_synthesize(job, segments, settings, vram)
    results["synthesize"] = synth_result
    _save_progress(job.job_id, "phase2", results)

    if not synth_result.success:
        log.error("pipeline_abort", reason="synthesize failed")
        clear_job_context()
        return results

    # M9: Lip-Sync (optional)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)

    if settings.enable_lipsync:
        # Tối ưu giải phóng GPU (Dynamic GPU Offloading) cho LatentSync (cần 8GB VRAM).
        # Always free STT/LLM/TTS before lip-sync — on a near-full GPU this avoids OOM
        # regardless of the declared VRAM_PROFILE.
        await unload_all_models(settings)
            
        lipsync_result = await run_lip_sync(job, settings, vram)
        results["lip_sync"] = lipsync_result
        _save_progress(job.job_id, "phase2", results)
        video_source = (
            os.path.join(temp_dir, "lipsync.mp4")
            if lipsync_result.success
            else os.path.join(temp_dir, "cleaned.mp4")
        )
    else:
        video_source = os.path.join(temp_dir, "cleaned.mp4")

    # If OCR failed or was skipped, cleaned.mp4 may not exist — fall back to original input
    if not os.path.exists(video_source):
        input_path = os.path.join(settings.data_dir, "input", job.filename)
        log.warning("cleaned_video_missing_fallback", missing=video_source, using=input_path)
        video_source = input_path

    _check_cancel(job.job_id)
    # M10: FFmpeg Mux
    output_dir = os.path.join(settings.data_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{job.base_name}_dubbed.mp4")
    new_vocal = os.path.join(temp_dir, "new_vocal.wav")
    bg_audio = os.path.join(temp_dir, "bg.wav")

    mux_start = time.monotonic()
    try:
        await asyncio.to_thread(mix_audio_to_video, video_source, new_vocal, bg_audio, output_path, settings.enable_bg_denoise)
        mux_success = os.path.exists(output_path)
        mux_error = None
    except Exception as e:
        mux_success = False
        mux_error = str(e)
        log.error("mux_failed", error=mux_error)

    # Also save the finished video to the user-chosen output folder (System Config), if set.
    # data/output stays the canonical copy the UI serves (preview/download/list).
    if mux_success:
        extra = (get_app_config().get("output_folder") or "").strip()
        if extra and os.path.abspath(extra) != os.path.abspath(output_dir):
            try:
                os.makedirs(extra, exist_ok=True)
                dest = os.path.join(extra, f"{job.base_name}_dubbed.mp4")
                await asyncio.to_thread(shutil.copy2, output_path, dest)
                log.info("output_copied_to_user_folder", dest=dest)
            except Exception as e:
                log.warning("output_copy_failed", folder=extra, error=str(e))

    results["mux"] = StageResult(
        stage="mux",
        success=mux_success,
        output_path=output_path if mux_success else None,
        duration_seconds=time.monotonic() - mux_start,
        error=mux_error
    )
    _save_progress(job.job_id, "phase2", results)

    log.info("pipeline_phase2_done", output=output_path)
    clear_job_context()
    return results
