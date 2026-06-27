from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class DemucsClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.demucs_api, settings)

    async def separate(self, video_path: str, output_dir: str) -> dict[str, str]:
        log.info("demucs_separate_start", video=video_path)
        result = await self.post_file("/separate", video_path, {"output_dir": output_dir})
        log.info("demucs_separate_done", vocal=result.get("vocal"))
        return {"vocal": result["vocal"], "background": result["background"]}
