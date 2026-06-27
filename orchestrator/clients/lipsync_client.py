from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class LipSyncClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.lipsync_api, settings)

    async def sync(self, video_path: str, audio_path: str, output_path: str) -> str:
        log.info("lipsync_start", video=video_path)
        payload = {
            "video_path": video_path,
            "audio_path": audio_path,
            "output_path": output_path,
        }
        result = await self.post_json("/sync", payload)
        out = result.get("output_path", output_path)
        log.info("lipsync_done", output=out)
        return out
