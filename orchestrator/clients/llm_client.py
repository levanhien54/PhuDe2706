import asyncio
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

_SEM = asyncio.Semaphore(10)

_TRANSLATE_PROMPT_VI = (
    "Dịch câu sau sang {target_lang} một cách tự nhiên, giữ đúng ngữ cảnh. "
    "Chỉ trả về bản dịch, không giải thích:\n\n{text}"
)

_TRANSLATE_PROMPT_EN = (
    "Translate the following text to {target_lang} naturally, preserving context. "
    "Return only the translation, no explanation:\n\n{text}"
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
        async with _SEM:
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

    async def translate_batch(
        self, segments: list[SrtSegment], target_lang: str = "Tiếng Việt"
    ) -> list[SrtSegment]:
        log.info("llm_translate_start", segment_count=len(segments), backend=self.settings.llm_backend, target_lang=target_lang)
        tasks = [self._translate_one(s.text, target_lang) for s in segments]
        translations = await asyncio.gather(*tasks)
        result = []
        for seg, trans in zip(segments, translations):
            result.append(SrtSegment(start=seg.start, end=seg.end, text=seg.text, translated=trans, speaker=seg.speaker))
        log.info("llm_translate_done")
        return result
