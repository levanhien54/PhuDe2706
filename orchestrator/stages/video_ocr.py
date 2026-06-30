import os, time, asyncio, shutil
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.video_process import remove_watermark_from_video
from orchestrator.stages.propainter_client import run_propainter_inference
from orchestrator.logger import get_logger

log = get_logger(__name__)

_OCR_VRAM_GB = 2.0


async def run_video_ocr(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    input_video = os.path.join(settings.data_dir, "input", job.filename)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    os.makedirs(temp_dir, exist_ok=True)
    output_video = os.path.join(temp_dir, "cleaned.mp4")

    # When OCR is disabled: pass original video through unchanged
    if not settings.enable_ocr:
        log.info("video_ocr_skip", msg="OCR disabled — copying original as cleaned.mp4")
        await asyncio.to_thread(shutil.copy2, input_video, output_video)
        return StageResult(
            stage="video_ocr",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )

    propainter_flag = "propainter" if settings.enable_propainter else f"ocr_{settings.ocr_mode}"
    resume_marker = os.path.join(temp_dir, f"cleaned.{propainter_flag}.done")
    if os.path.exists(output_video) and os.path.exists(resume_marker):
        log.info("video_ocr_resume", msg="Found existing cleaned.mp4, skipping inference")
        return StageResult(
            stage="video_ocr",
            success=True,
            output_path=output_video,
            duration_seconds=0,
        )

    try:
        async with vram.slot("paddleocr", _OCR_VRAM_GB):
            import sys
            python_exe = sys.executable
            script_path = os.path.join("orchestrator", "video_process.py")
            
            if settings.enable_propainter:
                mask_video = os.path.join(temp_dir, "mask.mp4")
                target, mask_flag = mask_video, "True"   # ProPainter consumes a mask video
            else:
                target, mask_flag = output_video, "False"  # blur/inpaint writes the cleaned video

            cmd = [python_exe, script_path, input_video, target, mask_flag, settings.ocr_mode]
            proc = await asyncio.create_subprocess_exec(*cmd)
            try:
                rc = await proc.wait()
            except asyncio.CancelledError:
                # Job cancelled mid-OCR: kill the child (EasyOCR/CRAFT holds GPU VRAM + spawns its
                # own ffmpeg) so it doesn't orphan and OOM the next job, then propagate the cancel.
                proc.kill()
                await proc.wait()
                raise
            if rc != 0:
                raise Exception(f"Video OCR subprocess failed with code {rc}")
            # A clean exit (rc==0) without an artifact means the subprocess died early
            # (e.g. a library exit(0)) — never treat that as success.
            if not os.path.exists(target):
                raise Exception(f"Video OCR exited cleanly but produced no {os.path.basename(target)}")

        if settings.enable_propainter:
            propainter_dir = os.path.join(os.path.dirname(settings.data_dir), "models", "propainter")
            async with vram.slot("propainter", 8.0):
                success = await run_propainter_inference(input_video, mask_video, output_video, propainter_dir)
                if not success:
                    raise Exception("ProPainter inference failed")

        open(resume_marker, 'w').close()
        return StageResult(
            stage="video_ocr",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("video_ocr_failed", error=str(e))
        return StageResult(stage="video_ocr", success=False, error=str(e))
