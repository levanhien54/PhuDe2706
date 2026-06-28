import os, time, asyncio
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

    propainter_flag = "propainter" if settings.enable_propainter else "ocr"
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
            if settings.enable_propainter:
                mask_video = os.path.join(temp_dir, "mask.mp4")
                # Generate mask only
                await asyncio.to_thread(remove_watermark_from_video, input_video, mask_video, True, settings)

                # Release paddleocr before running propainter to save VRAM
            else:
                await asyncio.to_thread(remove_watermark_from_video, input_video, output_video, False, settings)

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
