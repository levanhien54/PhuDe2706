import os
import sys
import subprocess
import asyncio
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

async def run_latentsync_inference(video_path: str, audio_path: str, output_path: str, settings: Settings):
    """
    Khởi chạy mô hình LatentSync thông qua Subprocess.
    Mã nguồn LatentSync dự kiến đặt tại: models/latentsync
    """
    log.info("latentsync_inference_start", video=video_path, audio=audio_path)
    
    latentsync_dir = os.path.join(settings.data_dir, "..", "models", "latentsync")
    latentsync_dir = os.path.abspath(latentsync_dir)
    
    if not os.path.exists(latentsync_dir):
        raise FileNotFoundError(f"Không tìm thấy thư mục mô hình LatentSync tại: {latentsync_dir}. Vui lòng chạy lại setup_native.ps1")

    # Kiểm tra weights
    ckpt_path = os.path.join(latentsync_dir, "checkpoints", "latentsync_unet.pt")
    if not os.path.exists(ckpt_path):
        raise FileNotFoundError(f"Chưa tải weights của LatentSync. Không tìm thấy: {ckpt_path}")

    # Cấu hình LatentSync (có thể cần điều chỉnh tuỳ theo version code trên github của Bytedance)
    config_path = os.path.join(latentsync_dir, "configs", "unet", "second_stage.yaml")
    
    cmd = [
        sys.executable, "-m", "scripts.inference",
        "--unet_config_path", config_path,
        "--inference_ckpt_path", ckpt_path,
        "--video_path", video_path,
        "--audio_path", audio_path,
        "--video_out_path", output_path
    ]

    log.info("latentsync_exec", cmd=" ".join(cmd), cwd=latentsync_dir)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=latentsync_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        log.error("latentsync_error", stderr=stderr.decode("utf-8", errors="ignore"))
        raise RuntimeError(f"LatentSync inference thất bại. Mã lỗi: {process.returncode}")
        
    log.info("latentsync_inference_done", output=output_path)
    return output_path
