import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.lipsync_client import LipSyncClient
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

    try:
        async with vram.slot("lipsync", _LIPSYNC_VRAM_GB):
            client = LipSyncClient(settings)
            await client.sync(cleaned_video, new_vocal, output_video)
        return StageResult(
            stage="lip_sync",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("lipsync_failed", error=str(e))
        return StageResult(stage="lip_sync", success=False, error=str(e))
