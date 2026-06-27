import asyncio
import os
import uuid
import argparse
from datetime import datetime

from orchestrator.config import get_settings
from orchestrator.logger import setup_logging, get_logger
from orchestrator.models import PipelineJob
from orchestrator.pipeline import run_pipeline

log = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Video Dubbing Orchestrator")
    parser.add_argument(
        "--video", type=str, default=None,
        help="Tên file video cụ thể trong data/input/ (bỏ trống để xử lý tất cả)",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return parser.parse_args()


async def main():
    args = parse_args()
    setup_logging(args.log_level)
    settings = get_settings()

    input_dir = os.path.join(settings.data_dir, "input")
    output_dir = os.path.join(settings.data_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if args.video:
        videos = [args.video] if args.video.endswith(".mp4") else []
    else:
        videos = [f for f in os.listdir(input_dir) if f.endswith(".mp4")]

    if not videos:
        log.warning("no_videos_found", input_dir=input_dir)
        print(f"Không tìm thấy video nào trong {input_dir}. Thả file .mp4 vào đó rồi chạy lại.")
        return

    log.info("batch_start", video_count=len(videos))

    for filename in videos:
        base_name = os.path.splitext(filename)[0]
        job = PipelineJob(
            job_id=str(uuid.uuid4())[:8],
            filename=filename,
            base_name=base_name,
            vram_profile=settings.vram_profile,
            created_at=datetime.utcnow(),
        )
        results = await run_pipeline(job, settings)

        print(f"\n=== Kết quả cho {filename} ===")
        for stage, result in results.items():
            status = "✓" if result.success else "✗"
            time_str = f"{result.duration_seconds:.1f}s" if result.duration_seconds else ""
            print(f"  {status} {stage:20s} {time_str}")
            if not result.success:
                print(f"    Lỗi: {result.error}")

    log.info("batch_done", video_count=len(videos))


if __name__ == "__main__":
    asyncio.run(main())
