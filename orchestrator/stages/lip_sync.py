import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.stages.latentsync_client import run_latentsync_inference
from orchestrator.stages.musetalk_client import run_musetalk_inference
from orchestrator.logger import get_logger

log = get_logger(__name__)

_LIPSYNC_VRAM_GB = 8.0


async def run_lip_sync(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    cleaned_video = os.path.join(temp_dir, "cleaned.mp4")
    new_vocal = os.path.join(temp_dir, "new_vocal.wav")
    output_video = os.path.join(temp_dir, "lipsync.mp4")

    if os.path.exists(output_video):
        log.info("lip_sync_resume", msg="Found existing lipsync.mp4, skipping inference")
        return StageResult(
            stage="lip_sync",
            success=True,
            output_path=output_video,
            duration_seconds=0,
        )

    engine = (settings.lipsync_engine or "latentsync").lower()
    inference = run_musetalk_inference if engine == "musetalk" else run_latentsync_inference

    try:
        async with vram.slot("lipsync", _LIPSYNC_VRAM_GB):
            log.info("lip_sync_engine", engine=engine)
            await inference(cleaned_video, new_vocal, output_video, settings)
        return StageResult(
            stage="lip_sync",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("lipsync_failed", error=str(e))
        return StageResult(stage="lip_sync", success=False, error=str(e))
