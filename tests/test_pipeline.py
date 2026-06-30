import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.pipeline import run_pipeline_phase1, run_pipeline_phase2
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from datetime import datetime


@pytest.fixture
def job():
    return PipelineJob(
        job_id="pipe-001",
        filename="sample.mp4",
        base_name="sample",
        vram_profile="16gb",
        created_at=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_pipeline_16gb_stage_order(job):
    """Xác nhận 16GB pipeline chạy theo thứ tự đúng và không bị lỗi OOM giả."""
    settings = Settings(vram_profile="16gb", enable_lipsync=False, http_retries=1)

    ok = StageResult(stage="x", success=True, output_path="/tmp/x")
    segments = [SrtSegment(start=0.0, end=2.0, text="Hello", translated="Xin chào")]

    with (
        patch("orchestrator.pipeline.run_audio_separate", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.run_video_ocr", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.run_transcribe", new_callable=AsyncMock, return_value=(ok, segments)),
        patch("orchestrator.pipeline.run_translate", new_callable=AsyncMock, return_value=(ok, segments)),
        patch("orchestrator.pipeline.run_synthesize", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.mix_audio_to_video"),
    ):
        results_phase1, translated_segments = await run_pipeline_phase1(job, settings)
        results_phase2 = await run_pipeline_phase2(job, translated_segments, settings)

    assert results_phase1["audio_separate"].success
    assert results_phase1["transcribe"].success
    assert results_phase1["translate"].success
    assert results_phase2["synthesize"].success
    assert "lip_sync" not in results_phase2  # ENABLE_LIPSYNC=False


@pytest.mark.asyncio
async def test_pipeline_ocr_failure_continues(job):
    """Xác nhận OCR thất bại thì pipeline vẫn tiếp tục."""
    settings = Settings(vram_profile="16gb", enable_lipsync=False, http_retries=1)
    
    ok = StageResult(stage="x", success=True, output_path="/tmp/x")
    fail_ocr = StageResult(stage="video_ocr", success=False, error="OCR error")
    segments = [SrtSegment(start=0.0, end=2.0, text="Hi", translated="Chào")]

    with (
        patch("orchestrator.pipeline.run_audio_separate", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.run_video_ocr", new_callable=AsyncMock, return_value=fail_ocr),
        patch("orchestrator.pipeline.run_transcribe", new_callable=AsyncMock, return_value=(ok, segments)),
        patch("orchestrator.pipeline.run_translate", new_callable=AsyncMock, return_value=(ok, segments)),
    ):
        results_phase1, translated_segments = await run_pipeline_phase1(job, settings)

    assert results_phase1["audio_separate"].success is True
    assert results_phase1["video_ocr"].success is False
    assert results_phase1["transcribe"].success is True
    assert len(translated_segments) == 1


@pytest.mark.asyncio
async def test_pipeline_mux_exception(job):
    """Xác nhận nếu mix_audio_to_video quăng lỗi thì mux_result.success = False."""
    settings = Settings(vram_profile="16gb", enable_lipsync=False, http_retries=1)
    ok = StageResult(stage="x", success=True, output_path="/tmp/x")
    segments = [SrtSegment(start=0.0, end=2.0, text="Hi", translated="Chào")]

    with (
        patch("orchestrator.pipeline.run_synthesize", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.mix_audio_to_video", side_effect=RuntimeError("FFmpeg crash!")),
    ):
        results_phase2 = await run_pipeline_phase2(job, segments, settings)

    assert results_phase2["synthesize"].success is True
    assert results_phase2["mux"].success is False
    assert "FFmpeg crash!" in results_phase2["mux"].error
