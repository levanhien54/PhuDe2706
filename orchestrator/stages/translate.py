import os, re, time, json
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.llm_client import LLMClient
from orchestrator.text_normalize import _CJK_RE, strip_cjk
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
    lang_slug = re.sub(r'[^\w]', '_', job.target_language.lower())
    # Include style in the cache key — otherwise re-running the same video with a different
    # "Phong cách dịch" would silently reuse the previous style's translation.
    style_slug = re.sub(r'[^\w]', '_', (job.target_style or "").lower())[:24]
    json_path = os.path.join(settings.data_dir, "temp", job.base_name, f"translate.{lang_slug}.{style_slug}.json")
    if os.path.exists(json_path):
        log.info("translate_resume", msg="Found existing translate.json, skipping inference")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            translated = [SrtSegment.model_validate(seg) for seg in data]
            # Old caches predate the CJK guard — strip any leaked CJK so a resume never feeds
            # Chinese/Japanese/Korean to the TTS engine.
            for s in translated:
                if s.translated and _CJK_RE.search(s.translated):
                    log.warning("cached_translation_cjk_leak", base=job.base_name)
                    s.translated = strip_cjk(s.translated)
            return StageResult(stage="translate", success=True, duration_seconds=0), translated
        except Exception as e:
            log.warning("translate_resume_failed", error=str(e))

    try:
        async with vram.slot("llm", _LLM_VRAM_GB):
            client = LLMClient(settings)
            merged_segments = merge_segments(segments)
            translated = await client.translate_batch(merged_segments, target_lang=job.target_language, target_style=job.target_style)

        # Every LLM failure path (down, malformed JSON, dropped item) silently falls back to the
        # SOURCE text. If that happened for EVERY segment, the "translation" is just the original
        # language — don't report success and ship an un-dubbed video. Fail loudly instead.
        n = len(translated)
        untranslated = sum(
            1 for o, t in zip(merged_segments, translated)
            if (not t.translated) or (t.translated.strip() == (o.text or "").strip())
        )
        if n > 0 and untranslated == n:
            log.error("translate_all_fallback", base=job.base_name, segments=n)
            return StageResult(
                stage="translate", success=False,
                error=f"Dịch thất bại: không segment nào được dịch ({n} câu) — LLM/Ollama có thể đang lỗi.",
            ), segments
        if untranslated:
            log.warning("translate_partial_fallback", base=job.base_name, untranslated=untranslated, total=n)

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump([s.model_dump() for s in translated], f, ensure_ascii=False, indent=2)

        result = StageResult(
            stage="translate",
            success=True,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, translated
    except Exception as e:
        log.error("translate_failed", error=str(e))
        return StageResult(stage="translate", success=False, error=str(e)), segments
