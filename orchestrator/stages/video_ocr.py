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

    import sys
    python_exe = sys.executable
    script_path = os.path.join("orchestrator", "video_process.py")

    async def _run_removal(target: str, mask_flag: str, mode: str) -> None:
        """Run the EasyOCR/CRAFT removal subprocess writing ``target``; raise on failure.

        ``mask_flag="False"`` detects + removes text in a single pass (blur/TELEA writes the
        cleaned video); ``mask_flag="True"`` only emits a mask video for ProPainter to consume.
        """
        cmd = [python_exe, script_path, input_video, target, mask_flag, mode]
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

    try:
        if settings.enable_propainter:
            # ProPainter (NTU S-Lab, models/propainter) is licensed for NON-COMMERCIAL use only;
            # the non-neural blur/TELEA path stays as the shipping-safe fallback below.
            mask_video = os.path.join(temp_dir, "mask.mp4")
            async with vram.slot("paddleocr", _OCR_VRAM_GB):
                await _run_removal(mask_video, "True", settings.ocr_mode)

            propainter_dir = os.path.join(os.path.dirname(settings.data_dir), "models", "propainter")
            success = False
            try:
                async with vram.slot("propainter", 8.0):
                    success = await run_propainter_inference(
                        input_video, mask_video, output_video, propainter_dir
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("propainter_error", error=str(e))
                success = False

            if not success:
                # ProPainter failed/OOM'd (common at HD without tiling) — fall back to the reliable
                # non-neural chain TELEA -> Gaussian blur so the job finishes instead of crashing.
                log.warning("propainter_fallback", msg="ProPainter failed; falling back to TELEA/blur")
                async with vram.slot("paddleocr", _OCR_VRAM_GB):
                    for fb_mode in ("inpaint", "blur"):
                        try:
                            await _run_removal(output_video, "False", fb_mode)
                            log.info("propainter_fallback_ok", mode=fb_mode)
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as fe:
                            log.error("propainter_fallback_failed", mode=fb_mode, error=str(fe))
                    else:
                        raise Exception(
                            "ProPainter failed and all non-neural fallbacks (TELEA, blur) failed"
                        )
        else:
            async with vram.slot("paddleocr", _OCR_VRAM_GB):
                await _run_removal(output_video, "False", settings.ocr_mode)

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
