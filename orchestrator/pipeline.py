import os
import asyncio
import time

from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager, get_vram_manager
from orchestrator.logger import get_logger, bind_job_context, clear_job_context
from orchestrator.stages import (
    run_audio_separate, run_transcribe, run_translate,
    run_synthesize, run_video_ocr, run_lip_sync,
)
from orchestrator.audio_sync import mix_audio_to_video

log = get_logger(__name__)

async def run_pipeline_phase1(job: PipelineJob, settings: Settings) -> tuple[dict[str, StageResult], list[SrtSegment]]:
    bind_job_context(job.job_id, job.filename)
    vram = get_vram_manager(settings)
    results: dict[str, StageResult] = {}
    
    log.info("pipeline_phase1_start", vram_profile=settings.vram_profile, target_lang=job.target_language)

    # M2 + M7 run concurrently
    sep_task = asyncio.create_task(run_audio_separate(job, settings, vram))
    ocr_task = asyncio.create_task(run_video_ocr(job, settings, vram))
    sep_result, ocr_result = await asyncio.gather(sep_task, ocr_task)

    results["audio_separate"] = sep_result
    results["video_ocr"] = ocr_result

    if not sep_result.success:
        log.error("pipeline_abort", reason="audio_separate failed")
        clear_job_context()
        return results, []

    # M3: WhisperX STT
    transcribe_result, segments = await run_transcribe(job, settings, vram)
    results["transcribe"] = transcribe_result

    if not transcribe_result.success or not segments:
        log.error("pipeline_abort", reason="transcribe failed or empty")
        clear_job_context()
        return results, []

    # M4: LLM Translate
    translate_result, translated_segments = await run_translate(job, segments, settings, vram)
    results["translate"] = translate_result

    if not translate_result.success:
        log.warning("translate_failed_using_original")
        translated_segments = segments  # fallback
        
    clear_job_context()
    return results, translated_segments


async def run_pipeline_phase2(job: PipelineJob, segments: list[SrtSegment], settings: Settings) -> dict[str, StageResult]:
    bind_job_context(job.job_id, job.filename)
    vram = get_vram_manager(settings)
    results: dict[str, StageResult] = {}
    
    log.info("pipeline_phase2_start", vram_profile=settings.vram_profile, lipsync=settings.enable_lipsync)

    # M5: TTS Synthesize
    synth_result = await run_synthesize(job, segments, settings, vram)
    results["synthesize"] = synth_result

    if not synth_result.success:
        log.error("pipeline_abort", reason="synthesize failed")
        clear_job_context()
        return results

    # M9: Lip-Sync (optional)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)

    if settings.enable_lipsync:
        lipsync_result = await run_lip_sync(job, settings, vram)
        results["lip_sync"] = lipsync_result
        video_source = (
            os.path.join(temp_dir, "lipsync.mp4")
            if lipsync_result.success
            else os.path.join(temp_dir, "cleaned.mp4")
        )
    else:
        video_source = os.path.join(temp_dir, "cleaned.mp4")

    # M10: FFmpeg Mux
    output_dir = os.path.join(settings.data_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{job.base_name}_dubbed.mp4")
    new_vocal = os.path.join(temp_dir, "new_vocal.wav")
    bg_audio = os.path.join(temp_dir, "bg.wav")

    mux_start = time.monotonic()
    mix_audio_to_video(video_source, new_vocal, bg_audio, output_path)
    results["mux"] = StageResult(
        stage="mux",
        success=os.path.exists(output_path),
        output_path=output_path,
        duration_seconds=time.monotonic() - mux_start,
    )

    log.info("pipeline_phase2_done", output=output_path)
    clear_job_context()
    return results
