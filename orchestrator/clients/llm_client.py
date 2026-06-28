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

_SYS_PROMPT_VI = (
    "Bạn là dịch giả phụ đề video chuyên nghiệp. Dịch sang {target_lang}. "
    "Luôn duy trì ngữ cảnh tự nhiên và chú ý 'speaker' (người nói) để dùng đại từ nhân xưng thống nhất.\n"
    "CHỈ TRẢ VỀ MẢNG JSON, mỗi phần tử gồm 'id' và 'translated'. Không kèm text nào khác."
)

_SYS_PROMPT_EN = (
    "You are a professional video subtitle translator. Translate into {target_lang}. "
    "Always maintain natural context and pay attention to 'speaker' for consistent pronouns.\n"
    "RETURN ONLY A JSON ARRAY, each element with 'id' and 'translated'. No other text."
)

_USER_PROMPT_TPL = (
    "Previous Context (Do not translate this part, use for reference only):\n{context}\n\n"
    "Subtitles to translate:\n{json_data}"
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

    async def _translate_batch_chunk(self, chunk: list[SrtSegment], target_lang: str, previous_context: str = "", retry: int = 0) -> list[str]:
        # Use 0-based IDs within chunk to avoid LLM reindexing issues
        input_data = [
            {"id": i, "speaker": s.speaker or "UNKNOWN", "text": s.text}
            for i, s in enumerate(chunk)
        ]

        is_vi = target_lang.lower().startswith("tiếng việt") or target_lang.lower() in ("vi", "vietnamese")
        sys_prompt = _SYS_PROMPT_VI.format(target_lang=target_lang) if is_vi else _SYS_PROMPT_EN.format(target_lang=target_lang)
        
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
                    "format": "json"
                }
                result = await self.post_json("/api/chat", payload)
                raw_out = result.get("message", {}).get("content", "").strip()

            import re
            match = re.search(r'\[.*\]', raw_out, re.DOTALL)
            if match:
                raw_out = match.group(0)

            parsed = json.loads(raw_out.strip())

            parsed_dict = {item["id"]: item.get("translated", "") for item in parsed if "id" in item}
            missing = [i for i in range(len(chunk)) if i not in parsed_dict]
            if missing:
                log.warning("batch_translation_partial", missing_count=len(missing), total=len(chunk))
            translations = [parsed_dict.get(i, chunk[i].text) for i in range(len(chunk))]

            return translations

        except Exception as e:
            if retry < 1:
                log.warning("batch_translation_failed_retry", error=str(e), chunk_size=len(chunk))
                await asyncio.sleep(1.0)
                return await self._translate_batch_chunk(chunk, target_lang, previous_context, retry=retry+1)
            
            log.warning("batch_translation_failed_fallback", error=str(e), chunk_size=len(chunk))
            await asyncio.sleep(1.0)
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

        translations = []
        previous_context = ""
        
        for chunk in chunks:
            chunk_trans = await self._translate_batch_chunk(chunk, target_lang, previous_context)
            translations.extend(chunk_trans)
            
            last_5 = list(zip(chunk[-5:], chunk_trans[-5:]))
            ctx_lines = [f"[{s.speaker or 'UNKNOWN'}] {s.text} -> {t}" for s, t in last_5]
            previous_context = "\n".join(ctx_lines)

        result = []
        for seg, trans in zip(segments, translations):
            result.append(SrtSegment(start=seg.start, end=seg.end, text=seg.text, translated=trans, speaker=seg.speaker))
        log.info("llm_translate_done")
        return result
