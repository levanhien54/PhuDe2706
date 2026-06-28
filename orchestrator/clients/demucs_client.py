from orchestrator.clients.base import BaseClient, ServiceUnavailableError
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class DemucsClient(BaseClient):
    def __init__(self, settings: Settings):
        self.is_local = settings.demucs_api == "local"
        if not self.is_local:
            super().__init__(settings.demucs_api, settings)
        else:
            self.settings = settings

    async def separate(self, video_path: str, output_dir: str) -> dict[str, str]:
        log.info("demucs_separate_start", video=video_path, local=self.is_local)
        
        if self.is_local:
            import asyncio
            import os
            # Run demucs natively via subprocess
            # htdemucs is the default model
            cmd = [
                "demucs",
                "--two-stems=vocals",
                "-n", "htdemucs",
                "-o", output_dir,
                video_path
            ]
            log.debug("demucs_cmd", cmd=" ".join(cmd))
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                log.error("demucs_local_failed", stderr=stderr.decode())
                raise ServiceUnavailableError(f"Local Demucs failed: {stderr.decode()}")
                
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            vocal_path = os.path.join(output_dir, "htdemucs", base_name, "vocals.wav")
            background_path = os.path.join(output_dir, "htdemucs", base_name, "no_vocals.wav")
            
            log.info("demucs_separate_done", vocal=vocal_path)
            return {"vocal": vocal_path, "background": background_path}
            
        else:
            if not await self.health_check():
                raise ServiceUnavailableError("Demucs service is not available")
            result = await self.post_file("/separate", video_path, {"output_dir": output_dir})
            log.info("demucs_separate_done", vocal=result.get("vocal"))
            return {"vocal": result["vocal"], "background": result["background"]}
