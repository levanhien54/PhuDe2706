import asyncio
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

import json
import re

# Ollama structured-output schema: forces a JSON ARRAY containing every item. Plain
# format:"json" lets the model return a single object and silently drop the rest of the
# batch (observed: qwen2.5 returns only id 0), which collapses the batch into N slow
# per-segment fallback calls.
_TRANSLATION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "translated": {"type": "string"}},
        "required": ["id", "translated"],
    },
}

# qwen2.5 (Chinese-origin) occasionally leaks Han characters / kana into non-Chinese
# output. Detect & strip for Latin-script targets so garbage never reaches TTS.
_CJK_RE = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")

# Override the local matcher/stripper with the comprehensive shared versions (also cover
# Hangul, CJK radicals and fullwidth) so this guard matches the final TTS-boundary strip.
from orchestrator.text_normalize import _CJK_RE, strip_cjk as _strip_cjk

def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))

_SEM: asyncio.Semaphore | None = None

def _get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(10)
    return _SEM

_SYS_PROMPT_VI = (
    "Bạn là một biên dịch viên phụ đề video chuyên nghiệp và đầy sáng tạo. Dịch sang {target_lang}. "
    "Luôn duy trì ngữ cảnh tự nhiên, chú ý 'speaker' (người nói) để dùng đại từ nhân xưng thống nhất. "
    "PHONG CÁCH YÊU CẦU: {target_style}. Hãy áp dụng phong cách này vào bản dịch thật tự nhiên. "
    "CHỈ THỊ ĐẶC BIỆT: "
    "1. KHỚP THỜI LƯỢNG: 'max_words' là số từ TỐI ĐA để lồng tiếng vừa khít thời lượng hình ảnh và nhạc nền gốc — đừng vượt quá. Nhưng TRONG giới hạn đó, hãy viết THẬT CÓ DUYÊN, tự nhiên, đậm PHONG CÁCH yêu cầu; dùng gần đủ ngân sách cho câu trọn ý và lôi cuốn, chỉ lược từ thừa/ý phụ khi sắp vượt. TUYỆT ĐỐI không dịch cụt lủn, khô cứng hay đánh mất sắc thái/cảm xúc của câu gốc. "
    "2. Bản địa hóa: Nếu có idiom, trò đùa hoặc tham chiếu văn hóa, hãy chuyển thể tự nhiên sang văn hóa đích thay vì dịch từng chữ. "
    "3. NGÔN NGỮ: Bản dịch CHỈ gồm chữ Tiếng Việt (chữ Latinh có dấu). TUYỆT ĐỐI không chèn chữ Hán/Trung Quốc, chữ Nhật hay ký tự ngôn ngữ khác.\n"
    "CHỈ TRẢ VỀ MẢNG JSON, mỗi phần tử gồm 'id' và 'translated'. Không kèm text nào khác."
)

_SYS_PROMPT_EN = (
    "You are a highly creative and professional video subtitle translator. Translate into {target_lang}. "
    "Always maintain natural context and pay attention to 'speaker' for consistent pronouns. "
    "REQUIRED STYLE: {target_style}. Apply this tone naturally to your translation. "
    "CRITICAL INSTRUCTIONS: "
    "1. DURATION MATCHING: 'max_words' is the MAXIMUM word count so the dub fits the original video/background-audio timing — do not exceed it. But WITHIN that limit, write naturally and engagingly in the REQUIRED STYLE; use close to the budget for a full, lively line, trimming filler only when about to exceed. NEVER produce a flat, choppy, stiff line or lose the original's tone/emotion. "
    "2. Localization: Localize jokes, idioms, and cultural references naturally into the target culture rather than translating literally.\n"
    "RETURN ONLY A JSON ARRAY, each element with 'id' and 'translated'. No other text."
)

_USER_PROMPT_TPL = (
    "Previous Context (Do not translate this part, use for reference only):\n{context}\n\n"
    "Subtitles to translate:\n{json_data}"
)

# Natural dubbing pace (~words/second). Used to turn each segment's duration into a hard
# word budget the LLM must respect so the dub fits the original video/background-audio timing.
_WORDS_PER_SEC = 5.5

def _word_budget(duration: float) -> int:
    return max(2, round((duration or 0) * _WORDS_PER_SEC))


class LLMClient(BaseClient):
    def __init__(self, settings: Settings):
        base_url = settings.vllm_host if settings.llm_backend == "vllm" else settings.ollama_host
        super().__init__(base_url, settings)
        self.settings = settings

    async def _translate_one(self, text: str, target_lang: str, target_style: str = "Tiêu chuẩn", duration: float | None = None) -> str:
        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        sys_prompt = _SYS_PROMPT_VI.format(target_lang=target_lang, target_style=target_style) if is_vi else _SYS_PROMPT_EN.format(target_lang=target_lang, target_style=target_style)
        item = {"id": 0, "text": text}
        if duration is not None:
            item["max_words"] = _word_budget(duration)
        user_prompt = _USER_PROMPT_TPL.format(
            context="None",
            json_data=json.dumps([item], ensure_ascii=False)
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]
        async with _get_sem():
            if self.settings.llm_backend == "vllm":
                payload = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "max_tokens": 512,
                    "temperature": 0.3,
                }
                result = await self.post_json("/v1/chat/completions", payload)
                raw_out = result["choices"][0]["message"]["content"].strip()
            else:
                payload = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "stream": False,
                    "format": _TRANSLATION_SCHEMA,
                }
                result = await self.post_json("/api/chat", payload)
                raw_out = result.get("message", {}).get("content", "").strip()
        import re
        try:
            parsed = json.loads(raw_out)
            if isinstance(parsed, dict):
                parsed = [parsed]
            # Guard parsed[0] is a dict: a vLLM backend (no enforced schema) may return a JSON
            # array of bare strings, and str.get would raise AttributeError (not in the except
            # tuple) — which would escape this method and abort the whole translate stage.
            if parsed and isinstance(parsed, list) and isinstance(parsed[0], dict) and parsed[0].get("translated"):
                return parsed[0]["translated"]
        except (json.JSONDecodeError, IndexError, KeyError):
            match = re.search(r'\[.*\]', raw_out, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                    if parsed and isinstance(parsed[0], dict) and parsed[0].get("translated"):
                        return parsed[0]["translated"]
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass
        return text

    async def _translate_batch_chunk(self, chunk: list[SrtSegment], target_lang: str, target_style: str = "Tiêu chuẩn", previous_context: str = "", retry: int = 0) -> list[str]:
        # Use 0-based IDs within chunk to avoid LLM reindexing issues
        input_data = [
            {"id": i, "speaker": s.speaker or "UNKNOWN", "max_words": _word_budget(s.duration), "text": s.text}
            for i, s in enumerate(chunk)
        ]

        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        sys_prompt = _SYS_PROMPT_VI.format(target_lang=target_lang, target_style=target_style) if is_vi else _SYS_PROMPT_EN.format(target_lang=target_lang, target_style=target_style)
        
        user_prompt = _USER_PROMPT_TPL.format(
            context=previous_context if previous_context else "None",
            json_data=json.dumps(input_data, ensure_ascii=False)
        )
        
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            if self.settings.llm_backend == "vllm":
                payload = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.3,
                }
                result = await self.post_json("/v1/chat/completions", payload)
                raw_out = result["choices"][0]["message"]["content"].strip()
            else:  # ollama
                payload = {
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "stream": False,
                    "format": _TRANSLATION_SCHEMA
                }
                result = await self.post_json("/api/chat", payload)
                raw_out = result.get("message", {}).get("content", "").strip()

            import re
            match = re.search(r'\[.*\]', raw_out, re.DOTALL)
            if match:
                raw_out = match.group(0)

            parsed = json.loads(raw_out.strip())
            # Normalize: if LLM returns a single object instead of array, wrap it
            if isinstance(parsed, dict):
                parsed = [parsed]

            # Coerce id to int — the model may return ids as strings, which would make
            # the int-based `missing` lookup below treat every item as missing.
            parsed_dict = {}
            for item in parsed:
                if isinstance(item, dict) and "id" in item and item.get("translated"):
                    try:
                        parsed_dict[int(item["id"])] = item["translated"]
                    except (ValueError, TypeError):
                        continue
            missing = [i for i in range(len(chunk)) if i not in parsed_dict]
            if missing:
                # The batch JSON dropped some items (common with long segments). Don't silently
                # keep the untranslated source — translate the missing ones individually.
                log.warning("batch_translation_partial", missing_count=len(missing), total=len(chunk))
                miss_tasks = [self._translate_one(chunk[i].text, target_lang, target_style, duration=chunk[i].duration) for i in missing]
                miss_results = await asyncio.gather(*miss_tasks, return_exceptions=True)
                for i, r in zip(missing, miss_results):
                    if isinstance(r, str) and r.strip():
                        parsed_dict[i] = r
                    else:
                        log.warning("single_translation_failed", index=i)
            translations = [parsed_dict.get(i, chunk[i].text) for i in range(len(chunk))]

            return translations

        except Exception as e:
            if retry < 1:
                log.warning("batch_translation_failed_retry", error=str(e), chunk_size=len(chunk))
                await asyncio.sleep(1.0)
                return await self._translate_batch_chunk(chunk, target_lang, target_style, previous_context, retry=retry+1)
            
            log.warning("batch_translation_failed_fallback", error=str(e), chunk_size=len(chunk))
            await asyncio.sleep(1.0)
            tasks = [self._translate_one(s.text, target_lang, target_style, duration=s.duration) for s in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                r if isinstance(r, str) else chunk[i].text
                for i, r in enumerate(results)
            ]

    async def translate_batch(
        self, segments: list[SrtSegment], target_lang: str = "Tiếng Việt", target_style: str = "Tiêu chuẩn"
    ) -> list[SrtSegment]:
        log.info("llm_translate_start", segment_count=len(segments), backend=self.settings.llm_backend, target_lang=target_lang)
        chunk_size = 20
        chunks = [segments[i:i+chunk_size] for i in range(0, len(segments), chunk_size)]

        # Build each chunk's reference context from the PRECEDING source lines (known upfront)
        # so all chunks translate concurrently, instead of each waiting on the previous chunk's
        # output. Trade-off: cross-chunk context is source-only, not the prior translation.
        ctx_window = 5
        contexts = [""]
        for ci in range(1, len(chunks)):
            prev_tail = chunks[ci - 1][-ctx_window:]
            contexts.append("\n".join(f"[{s.speaker or 'UNKNOWN'}] {s.text}" for s in prev_tail))

        sem = asyncio.Semaphore(max(1, self.settings.llm_concurrency))

        async def _run(chunk, ctx):
            async with sem:
                return await self._translate_batch_chunk(chunk, target_lang, target_style, ctx)

        chunk_results = await asyncio.gather(*[_run(c, ctx) for c, ctx in zip(chunks, contexts)])
        translations = [t for cr in chunk_results for t in cr]

        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        result = []
        for seg, trans in zip(segments, translations):
            result.append(SrtSegment(start=seg.start, end=seg.end, text=seg.text, translated=trans, speaker=seg.speaker))

        # Wrong-script guard: qwen occasionally leaks Han/kana into Vietnamese output.
        # Re-translate the offending line once; strip as a last resort so TTS never speaks garbage.
        if is_vi:
            for seg in result:
                if seg.translated and _has_cjk(seg.translated):
                    log.warning("translation_cjk_leak", original=seg.text[:40])
                    # Never let a single repair failure abort the stage — fall back to stripping
                    # CJK so TTS still gets clean text. (CancelledError is BaseException, so a
                    # job cancel still propagates through this except Exception.)
                    try:
                        fixed = await self._translate_one(seg.text, target_lang, target_style, duration=seg.duration)
                    except Exception as e:
                        log.warning("translation_cjk_repair_failed", error=str(e))
                        fixed = None
                    seg.translated = fixed if (fixed and not _has_cjk(fixed)) else _strip_cjk(seg.translated)

        log.info("llm_translate_done")
        return result
