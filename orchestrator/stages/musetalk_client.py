"""MuseTalk lip-sync client (faster single-pass alternative to LatentSync).

⚠️ CHƯA TEST TRÊN GPU — verify trước khi dùng thật. MuseTalk (TMElyralab/MuseTalk) nhận input
qua một file YAML (khác LatentSync dùng CLI args) và tên file output tuỳ version. Hai chỗ dễ sai
đã được cô lập + đánh dấu MUSETALK-CMD / MUSETALK-OUTPUT bên dưới để sửa nhanh khi chạy thực tế.

Mã nguồn MuseTalk dự kiến đặt tại: models/musetalk (tải bằng setup_native.ps1)."""
import os
import sys
import glob
import subprocess
import asyncio

from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


async def run_musetalk_inference(video_path: str, audio_path: str, output_path: str, settings: Settings):
    log.info("musetalk_inference_start", video=video_path, audio=audio_path)

    musetalk_dir = os.path.abspath(os.path.join(settings.data_dir, "..", "models", "musetalk"))
    if not os.path.exists(musetalk_dir):
        raise FileNotFoundError(
            f"Không tìm thấy thư mục mô hình MuseTalk tại: {musetalk_dir}. Chạy lại setup_native.ps1"
        )

    result_dir = os.path.dirname(output_path)
    os.makedirs(result_dir, exist_ok=True)

    # --- MUSETALK-CMD (verify): MuseTalk nhận input qua YAML, không qua CLI args như LatentSync.
    # Ghi một inference-config tạm rồi gọi scripts.inference. Schema YAML + tên module có thể khác
    # tuỳ version MuseTalk đã cài — chỉnh 3 dòng dưới nếu chạy thật báo lỗi.
    inference_yaml = os.path.join(result_dir, f"musetalk_{os.path.basename(output_path)}.yaml")
    with open(inference_yaml, "w", encoding="utf-8") as f:
        f.write("task_0:\n")
        f.write(f'  video_path: "{video_path}"\n')
        f.write(f'  audio_path: "{audio_path}"\n')

    cmd = [
        sys.executable, "-m", "scripts.inference",
        "--inference_config", inference_yaml,
        "--result_dir", result_dir,
    ]
    # --- end MUSETALK-CMD ---

    log.info("musetalk_exec", cmd=" ".join(cmd), cwd=musetalk_dir)
    process = await asyncio.create_subprocess_exec(
        *cmd, cwd=musetalk_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        # Job cancelled mid-inference: kill the MuseTalk child (~6-8GB VRAM) so it does not
        # orphan and OOM the next job, then propagate the cancel.
        process.kill()
        await process.wait()
        raise

    if process.returncode != 0:
        log.error("musetalk_error", stderr=stderr.decode("utf-8", errors="ignore"))
        raise RuntimeError(f"MuseTalk inference thất bại. Mã lỗi: {process.returncode}")

    # --- MUSETALK-OUTPUT (verify): MuseTalk đặt tên output theo task, không đúng output_path.
    # Nếu đúng chỗ rồi thì thôi; nếu không, lấy .mp4 mới nhất trong result_dir và đổi tên.
    if not os.path.exists(output_path):
        produced = sorted(
            (p for p in glob.glob(os.path.join(result_dir, "*.mp4")) if p != output_path),
            key=os.path.getmtime,
        )
        if not produced:
            raise RuntimeError(f"MuseTalk chạy xong (rc=0) nhưng không thấy file .mp4 trong {result_dir}")
        os.replace(produced[-1], output_path)
    # --- end MUSETALK-OUTPUT ---

    log.info("musetalk_inference_done", output=output_path)
    return output_path
