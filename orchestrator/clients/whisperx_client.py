from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)


class WhisperXClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.whisperx_api, settings)

    async def transcribe(self, audio_path: str) -> list[SrtSegment]:
        log.info("whisperx_transcribe_start", audio=audio_path)
        result = await self.post_file("/transcribe", audio_path)
        segments = [
            SrtSegment(start=s["start"], end=s["end"], text=s["text"].strip())
            for s in result.get("segments", [])
            if s.get("text", "").strip()
        ]
        log.info("whisperx_transcribe_done", segment_count=len(segments))
        return segments
