from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger
from orchestrator.text_normalize import normalize_for_tts

log = get_logger(__name__)

_LANG_MAP = {
    "tiếng việt": "vi",
    "vietnamese": "vi",
    "vi": "vi",
    "english": "en",
    "en": "en",
    "日本語": "ja",
    "japanese": "ja",
    "ja": "ja",
    "中文": "zh",
    "chinese": "zh",
    "zh": "zh",
    "한국어": "ko",
    "korean": "ko",
    "ko": "ko",
    "français": "fr",
    "french": "fr",
    "fr": "fr",
    "deutsch": "de",
    "german": "de",
    "de": "de",
}


def _to_lang_code(lang: str) -> str:
    code = _LANG_MAP.get((lang or "").lower())
    if code is None:
        # Don't silently dub an unmapped target as English — let OmniVoice go language-agnostic.
        log.warning("tts_unmapped_language", lang=lang)
        return ""
    return code


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
        ref_text: str | None = None,
    ) -> str:
        log.info("tts_synthesize", engine=self.settings.tts_engine, text_len=len(text))
        lang_code = _to_lang_code(language)
        # Expand numbers / %, acronyms (AI -> "ây ai"), loanwords so the TTS reads them
        # correctly instead of spelling digits or mis-reading "AI" as the word "ai".
        text = normalize_for_tts(text, lang_code)

        if self.settings.tts_engine == "omnivoice":
            payload = {
                "text": text,
                "language": lang_code,
                "output_path": output_path,
                "target_duration": target_duration,
            }
            if reference_audio is not None:
                payload["reference_audio"] = reference_audio
            if ref_text:
                payload["ref_text"] = ref_text  # lets OmniVoice skip ASR auto-transcribe (cloning on)
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
