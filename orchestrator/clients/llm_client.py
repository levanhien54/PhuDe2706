import asyncio
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

import json

_SEM: asyncio.Semaphore | None = None

def _get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(10)
    return _SEM

_TRANSLATE_PROMPT_VI = (
    "Dịch câu sau sang {target_lang} một cách tự nhiên, giữ đúng ngữ cảnh. "
    "Chỉ trả về bản dịch, không giải thích:\n\n{text}"
)

_TRANSLATE_PROMPT_EN = (
    "Translate the following text to {target_lang} naturally, preserving context. "
    "Return only the translation, no explanation:\n\n{text}"
)

_BATCH_PROMPT_VI = (
    "Bạn là dịch giả chuyên nghiệp. Dịch các phụ đề sau sang {target_lang}. "
    "Giữ ngữ cảnh tự nhiên. "
    "Trả về KẾT QUẢ ĐÚNG ĐỊNH DẠNG JSON array, mỗi phần tử có 'id' và 'translated'. "
    "Không thêm markdown, giải thích hoặc text ngoài JSON array.\n"
    "Input JSON:\n{json_data}"
)

_BATCH_PROMPT_EN = (
    "You are a professional translator. Translate the following subtitles into {target_lang}. "
    "Keep the context natural. "
    "Return STRICTLY a valid JSON array where each element has 'id' and 'translated' keys. "
    "No markdown, explanations, or text outside the JSON array.\n"
    "Input JSON:\n{json_data}"
)


class LLMClient(BaseClient):
    def __init__(self, settings: Settings):
        base_url = settings.vllm_host if settings.llm_backend == "vllm" else settings.ollama_host
        super().__init__(base_url, settings)
        self.settings = settings

    async def _translate_one(self, text: str, target_lang: str) -> str:
        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        prompt_tpl = _TRANSLATE_PROMPT_VI if is_vi else _TRANSLATE_PROMPT_EN
        prompt = prompt_tpl.format(text=text, target_lang=target_lang)
        async with _get_sem():
            if self.settings.llm_backend == "vllm":
                payload = {
                    "model": self.settings.llm_model,
                    "prompt": prompt,
                    "max_tokens": 512,
                    "temperature": 0.3,
                }
                result = await self.post_json("/v1/completions", payload)
                return result["choices"][0]["text"].strip()
            else:  # ollama
                payload = {
                    "model": self.settings.llm_model,
                    "prompt": prompt,
                    "stream": False,
                }
                result = await self.post_json("/api/generate", payload)
                return result.get("response", "").strip()

    async def _translate_batch_chunk(self, chunk: list[SrtSegment], target_lang: str) -> list[str]:
        # Use 0-based IDs within chunk to avoid LLM reindexing issues
        input_data = [
            {"id": i, "text": s.text}
            for i, s in enumerate(chunk)
        ]

        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        batch_tpl = _BATCH_PROMPT_VI if is_vi else _BATCH_PROMPT_EN
        prompt = batch_tpl.format(target_lang=target_lang, json_data=json.dumps(input_data, ensure_ascii=False))

        try:
            if self.settings.llm_backend == "vllm":
                payload = {
                    "model": self.settings.llm_model,
                    "prompt": prompt,
                    "max_tokens": 2048,
                    "temperature": 0.3,
                }
                result = await self.post_json("/v1/completions", payload)
                raw_out = result["choices"][0]["text"].strip()
            else:  # ollama
                payload = {
                    "model": self.settings.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                result = await self.post_json("/api/generate", payload)
                raw_out = result.get("response", "").strip()

            # Strip markdown code block if present
            if raw_out.startswith("```json"):
                raw_out = raw_out[7:]
            if raw_out.startswith("```"):
                raw_out = raw_out[3:]
            if raw_out.endswith("```"):
                raw_out = raw_out[:-3]

            parsed = json.loads(raw_out.strip())

            parsed_dict = {item["id"]: item.get("translated", "") for item in parsed if "id" in item}
            translations = [parsed_dict.get(i, chunk[i].text) for i in range(len(chunk))]

            return translations

        except Exception as e:
            log.warning("batch_translation_failed_fallback", error=str(e), chunk_size=len(chunk))
            await asyncio.sleep(1.0)  # brief backoff before retrying individually
            tasks = [self._translate_one(s.text, target_lang) for s in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                r if isinstance(r, str) else chunk[i].text
                for i, r in enumerate(results)
            ]

    async def translate_batch(
        self, segments: list[SrtSegment], target_lang: str = "Tiếng Việt"
    ) -> list[SrtSegment]:
        log.info("llm_translate_start", segment_count=len(segments), backend=self.settings.llm_backend, target_lang=target_lang)
        chunk_size = 20
        chunks = [segments[i:i+chunk_size] for i in range(0, len(segments), chunk_size)]

        # Limit concurrent batch requests with semaphore
        batch_sem = asyncio.Semaphore(3)

        async def _run_chunk(chunk):
            async with batch_sem:
                return await self._translate_batch_chunk(chunk, target_lang)

        chunk_results = await asyncio.gather(*[
            _run_chunk(chunk)
            for chunk in chunks
        ])

        translations = [t for chunk_trans in chunk_results for t in chunk_trans]
        result = []
        for seg, trans in zip(segments, translations):
            result.append(SrtSegment(start=seg.start, end=seg.end, text=seg.text, translated=trans, speaker=seg.speaker))
        log.info("llm_translate_done")
        return result
