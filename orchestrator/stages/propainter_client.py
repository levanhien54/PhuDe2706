import os
import sys
import time
import asyncio
from orchestrator.logger import get_logger

log = get_logger(__name__)

async def run_propainter_inference(
    video_path: str, mask_path: str, output_path: str, propainter_dir: str,
    *, fp16: bool = True, resize_ratio: float = 1.0, subvideo_length: int = 80,
) -> bool:
    """
    Calls the ProPainter inference script natively via a subprocess.
    Requires ProPainter repository cloned in models/propainter.

    HD/OOM mitigation (sczhou/ProPainter flags — verify against the installed version):
      fp16 -> --fp16 (half precision), resize_ratio -> --resize_ratio (downscale),
      subvideo_length -> --subvideo_length (frames per temporal chunk; smaller = less VRAM).
    """
    log.info("propainter_start", video=video_path, mask=mask_path,
             fp16=fp16, resize_ratio=resize_ratio, subvideo_length=subvideo_length)
    inference_script = os.path.join(propainter_dir, "inference_propainter.py")

    if not os.path.exists(inference_script):
        log.error("propainter_missing", path=inference_script)
        return False

    temp_out_dir = os.path.join(os.path.dirname(output_path), "propainter_out")
    os.makedirs(temp_out_dir, exist_ok=True)

    cmd = [
        sys.executable, inference_script,
        "--video", video_path,
        "--mask", mask_path,
        "--output", temp_out_dir,
        "--resize_ratio", str(resize_ratio),
        "--subvideo_length", str(int(subvideo_length)),
    ]
    if fp16:
        cmd.append("--fp16")

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=propainter_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            log.error("propainter_failed", error=stderr.decode('utf-8', errors='replace'))
            return False
            
        out_files = [f for f in os.listdir(temp_out_dir) if f.endswith(".mp4") or f.endswith(".avi")]
        if out_files:
            generated_file = os.path.join(temp_out_dir, out_files[0])
            import shutil
            shutil.move(generated_file, output_path)
            log.info("propainter_done", output=output_path)
            return True
        else:
            log.error("propainter_no_output", temp_dir=temp_out_dir)
            return False

    except asyncio.CancelledError:
        # Job cancelled mid-inference: kill the ProPainter child (holds ~8GB VRAM) so it does
        # not orphan and OOM the next job, then propagate the cancel.
        if proc is not None:
            proc.kill()
            await proc.wait()
        raise
    except Exception as e:
        log.error("propainter_exception", error=str(e))
        return False
