import sys
import shutil
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
            cmd = [
                sys.executable, "-m", "demucs",
                "--two-stems=vocals",
                "-n", "htdemucs_ft",
                "-o", output_dir,
                video_path
            ]
            log.debug("demucs_cmd", cmd=" ".join(str(c) for c in cmd))

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            try:
                stdout, stderr = await process.communicate()
            except asyncio.CancelledError:
                # Job cancelled mid-separation: kill the demucs child (GPU) so it doesn't orphan.
                process.kill()
                await process.wait()
                raise

            if process.returncode != 0:
                out_str = stdout.decode(errors='replace')
                err_str = stderr.decode(errors='replace')
                log.error("demucs_local_failed", stdout=out_str, stderr=err_str)
                raise ServiceUnavailableError(f"Local Demucs failed: {err_str} | {out_str}")

            base_name = os.path.splitext(os.path.basename(video_path))[0]
            src_vocal = os.path.join(output_dir, "htdemucs_ft", base_name, "vocals.wav")
            src_bg = os.path.join(output_dir, "htdemucs_ft", base_name, "no_vocals.wav")
            dst_vocal = os.path.join(output_dir, "vocal.wav")
            dst_bg = os.path.join(output_dir, "bg.wav")
            shutil.move(src_vocal, dst_vocal)
            shutil.move(src_bg, dst_bg)
            shutil.rmtree(os.path.join(output_dir, "htdemucs_ft"), ignore_errors=True)

            log.info("demucs_separate_done", vocal=dst_vocal)
            return {"vocal": dst_vocal, "background": dst_bg}
            
        else:
            if not await self.health_check():
                raise ServiceUnavailableError("Demucs service is not available")
            result = await self.post_file("/separate", video_path, {"output_dir": output_dir})
            log.info("demucs_separate_done", vocal=result.get("vocal"))
            return {"vocal": result["vocal"], "background": result["background"]}
