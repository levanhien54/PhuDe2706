from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

_LANG_MAP = {
    "tiếng việt": "vi",
    "vi": "vi",
    "english": "en",
    "en": "en",
    "日本語": "ja",
    "ja": "ja",
    "中文": "zh",
    "zh": "zh",
    "한국어": "ko",
    "ko": "ko",
    "français": "fr",
    "fr": "fr",
    "deutsch": "de",
    "de": "de",
}


def _to_lang_code(lang: str) -> str:
    return _LANG_MAP.get(lang.lower(), "en")


class TTSClient(BaseClient):
    """Unified TTS client. Routes to omnivoice or gpt_sovits based on settings.tts_engine."""

    def __init__(self, settings: Settings):
        if settings.tts_engine == "omnivoice":
            super().__init__(settings.omnivoice_api, settings)
        else:
            super().__init__(settings.tts_api, settings)
        self.settings = settings

    async def synthesize(
        self,
        text: str,
        reference_audio: str | None,
        output_path: str,
        target_duration: float,
        language: str = "vi",
    ) -> str:
        log.info("tts_synthesize", engine=self.settings.tts_engine, text_len=len(text))
        lang_code = _to_lang_code(language)

        if self.settings.tts_engine == "omnivoice":
            payload = {
                "text": text,
                "language": lang_code,
                "output_path": output_path,
            }
            if reference_audio is not None:
                payload["reference_audio"] = reference_audio
            result = await self.post_json("/v1/audio/speech", payload)
        else:  # gpt_sovits
            payload = {
                "text": text,
                "text_language": lang_code,
                "output_path": output_path,
            }
            if reference_audio is not None:
                payload["refer_wav_path"] = reference_audio
            result = await self.post_json("/tts", payload)

        generated_path = result.get("output_path", output_path)
        log.info("tts_synthesize_done", output=generated_path)
        return generated_path
