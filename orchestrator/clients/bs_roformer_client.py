"""BS-Roformer vocal separation (SOTA alternative to Demucs).

⚠️ CHƯA TEST TRÊN GPU — verify trước khi dùng. Dùng gói `audio-separator`
(beveradb/python-audio-separator) wrap BS-Roformer. Tên model (.ckpt) và tên file output tuỳ
phiên bản; hai chỗ dễ sai đã cô lập + đánh dấu BSROFORMER-MODEL / BSROFORMER-OUTPUT.

Cùng interface với DemucsClient: separate(video_path, output_dir) -> {"vocal","background"}."""
import os
import sys
import glob
import shutil
import asyncio

from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class BSRoformerClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def separate(self, video_path: str, output_dir: str) -> dict[str, str]:
        log.info("bsroformer_separate_start", video=video_path)
        os.makedirs(output_dir, exist_ok=True)
        raw_dir = os.path.join(output_dir, "bsroformer_out")
        os.makedirs(raw_dir, exist_ok=True)

        # --- BSROFORMER-MODEL (verify): cách gọi CLI + tên model của audio-separator ---
        model = self.settings.separation_model or "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
        cmd = [
            sys.executable, "-m", "audio_separator.utils.cli", video_path,
            "--model_filename", model,
            "--output_dir", raw_dir,
            "--output_format", "WAV",
        ]
        # --- end BSROFORMER-MODEL ---

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            # Job cancelled mid-separation: kill the child (GPU) so it doesn't orphan.
            proc.kill()
            await proc.wait()
            raise

        if proc.returncode != 0:
            raise RuntimeError(
                f"BS-Roformer separation failed: {stderr.decode('utf-8', errors='replace')}"
            )

        # --- BSROFORMER-OUTPUT (verify): audio-separator đặt tên *(Vocals)* / *(Instrumental)* ---
        vocals = glob.glob(os.path.join(raw_dir, "*Vocals*.wav")) or glob.glob(os.path.join(raw_dir, "*vocals*.wav"))
        instr = glob.glob(os.path.join(raw_dir, "*Instrumental*.wav")) or glob.glob(os.path.join(raw_dir, "*instrumental*.wav"))
        if not vocals or not instr:
            raise RuntimeError(
                f"BS-Roformer chạy xong (rc=0) nhưng không thấy stem Vocals/Instrumental trong {raw_dir}"
            )
        dst_vocal = os.path.join(output_dir, "vocal.wav")
        dst_bg = os.path.join(output_dir, "bg.wav")
        shutil.move(vocals[0], dst_vocal)
        shutil.move(instr[0], dst_bg)
        shutil.rmtree(raw_dir, ignore_errors=True)
        # --- end BSROFORMER-OUTPUT ---

        log.info("bsroformer_separate_done", vocal=dst_vocal)
        return {"vocal": dst_vocal, "background": dst_bg}
