import os
import sys
import time
import asyncio
from orchestrator.logger import get_logger

log = get_logger(__name__)

async def run_propainter_inference(
    video_path: str, mask_path: str, output_path: str, propainter_dir: str
) -> bool:
    """
    Calls the ProPainter inference script natively via a subprocess.
    Requires ProPainter repository cloned in models/propainter.
    """
    log.info("propainter_start", video=video_path, mask=mask_path)
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
        "--output", temp_out_dir
    ]

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

    except Exception as e:
        log.error("propainter_exception", error=str(e))
        return False
