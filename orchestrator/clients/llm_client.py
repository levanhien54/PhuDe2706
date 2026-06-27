import asyncio
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TRANSLATE_PROMPT = (
    "Dịch câu sau sang {target_lang} một cách tự nhiên, giữ đúng ngữ cảnh. "
    "Chỉ trả về bản dịch, không giải thích:\n\n{text}"
)


class LLMClient(BaseClient):
    def __init__(self, settings: Settings):
        base_url = settings.vllm_host if settings.llm_backend == "vllm" else settings.ollama_host
        super().__init__(base_url, settings)
        self.settings = settings

    async def _translate_one(self, text: str, target_lang: str) -> str:
        prompt = _TRANSLATE_PROMPT.format(text=text, target_lang=target_lang)
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
