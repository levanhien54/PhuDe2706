import time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.llm_client import LLMClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_LLM_VRAM_GB = 9.0

def merge_segments(segments: list[SrtSegment], max_gap: float = 0.8) -> list[SrtSegment]:
    if not segments:
        return []
    
    merged = [segments[0].model_copy()]  # copy so we never mutate caller's objects
    for curr in segments[1:]:
        prev = merged[-1]

        # Check if same speaker and gap is small
        same_speaker = prev.speaker == curr.speaker
        small_gap = (curr.start - prev.end) <= max_gap

        if same_speaker and small_gap:
            prev.end = curr.end
            prev.text = f"{prev.text} {curr.text}".strip()
            if prev.translated and curr.translated:
                prev.translated = f"{prev.translated} {curr.translated}".strip()
        else:
            merged.append(curr.model_copy())

    return merged


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
            merged_segments = merge_segments(segments)
            translated = await client.translate_batch(merged_segments, target_lang=job.target_language)
        result = StageResult(
            stage="translate",
            success=True,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, translated
    except Exception as e:
        log.error("translate_failed", error=str(e))
        return StageResult(stage="translate", success=False, error=str(e)), segments
