import time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.llm_client import LLMClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_LLM_VRAM_GB = 9.0


async def run_translate(
    job: PipelineJob,
    segments: list[SrtSegment],
    settings: Settings,
    vram: VRAMManager,
) -> tuple[StageResult, list[SrtSegment]]:
    start_time = time.monotonic()
    try:
        async with vram.slot("llm", _LLM_VRAM_GB):
            client = LLMClient(settings)
            translated = await client.translate_batch(segments, target_lang=job.target_language)
        result = StageResult(
            stage="translate",
            success=True,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, translated
    except Exception as e:
        log.error("translate_failed", error=str(e))
        return StageResult(stage="translate", success=False, error=str(e)), segments
