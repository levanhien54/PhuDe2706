import os, time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.whisperx_client import WhisperXClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_WHISPERX_VRAM_GB = 5.0


async def run_transcribe(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> tuple[StageResult, list[SrtSegment]]:
    start_time = time.monotonic()
    vocal_path = os.path.join(settings.data_dir, "temp", job.base_name, "vocal.wav")

    try:
        async with vram.slot("whisperx", _WHISPERX_VRAM_GB):
            client = WhisperXClient(settings)
            segments = await client.transcribe(vocal_path)
        result = StageResult(
            stage="transcribe",
            success=True,
            output_path=vocal_path,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, segments
    except Exception as e:
        log.error("transcribe_failed", error=str(e))
        return StageResult(stage="transcribe", success=False, error=str(e)), []
