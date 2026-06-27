import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.demucs_client import DemucsClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_DEMUCS_VRAM_GB = 3.0


async def run_audio_separate(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    video_path = os.path.join(settings.data_dir, "input", job.filename)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with vram.slot("demucs", _DEMUCS_VRAM_GB):
            client = DemucsClient(settings)
            result = await client.separate(video_path, temp_dir)
        return StageResult(
            stage="audio_separate",
            success=True,
            output_path=result["vocal"],
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("audio_separate_failed", error=str(e))
        return StageResult(stage="audio_separate", success=False, error=str(e))
