"""ProPainter watermark-removal fallback (v2.0 robustness).

ProPainter frequently OOMs at HD without tiling. Rather than failing the whole dubbing job,
run_video_ocr must fall back to the non-neural TELEA -> Gaussian-blur chain so the job still
produces a cleaned video. These tests mock the removal subprocess + ProPainter inference so no
GPU/model weights are needed."""
import asyncio
import os
from unittest.mock import patch

from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.models import PipelineJob
from orchestrator.stages import video_ocr


class _FakeProc:
    """Async subprocess stand-in that 'succeeds' and creates its target artifact (argv[3])."""

    def __init__(self, target):
        self._target = target

    async def wait(self):
        open(self._target, "w").close()  # emulate the child producing its output file
        return 0

    def kill(self):  # pragma: no cover - only used on cancel
        pass


def _setup(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "input").mkdir(parents=True)
    (data_dir / "temp").mkdir(parents=True)
    (data_dir / "input" / "v.mp4").write_bytes(b"x")
    settings = Settings(
        vram_profile="16gb", enable_ocr=True, enable_propainter=True,
        data_dir=str(data_dir), _env_file=None,
    )
    vram = VRAMManager(settings)
    job = PipelineJob(job_id="j1", filename="v.mp4", base_name="v")
    cleaned = data_dir / "temp" / "v" / "cleaned.mp4"
    return settings, vram, job, str(cleaned)


def _record_subprocess(calls):
    # patch() wraps the async create_subprocess_exec as an AsyncMock, so the side_effect returns
    # the proc object directly (AsyncMock makes the call awaitable).
    def fake_create(*args, **kwargs):
        # cmd = [python, script, input, target, mask_flag, mode]
        target, mask_flag, mode = args[3], args[4], args[5]
        calls.append({"mask_flag": mask_flag, "mode": mode, "target": target})
        return _FakeProc(target)
    return fake_create


def test_falls_back_to_non_neural_when_propainter_fails(tmp_path):
    settings, vram, job, cleaned = _setup(tmp_path)
    calls = []

    async def propainter_fails(*a, **k):
        return False

    with patch("asyncio.create_subprocess_exec", side_effect=_record_subprocess(calls)), \
         patch("orchestrator.stages.video_ocr.run_propainter_inference", new=propainter_fails):
        result = asyncio.run(video_ocr.run_video_ocr(job, settings, vram))

    assert result.success is True, f"stage failed instead of falling back: {result.error}"
    assert calls[0]["mask_flag"] == "True", "first pass should generate the ProPainter mask"
    fallback = [c for c in calls if c["mask_flag"] == "False"]
    assert fallback, "no non-neural fallback subprocess ran after ProPainter failure"
    assert fallback[0]["mode"] == "inpaint", "fallback should try TELEA (inpaint) before blur"
    assert os.path.exists(cleaned), "fallback did not produce cleaned.mp4"


def test_no_fallback_when_propainter_succeeds(tmp_path):
    settings, vram, job, cleaned = _setup(tmp_path)
    calls = []

    async def propainter_ok(input_v, mask_v, out_v, prop_dir, **kwargs):
        open(out_v, "w").close()
        return True

    with patch("asyncio.create_subprocess_exec", side_effect=_record_subprocess(calls)), \
         patch("orchestrator.stages.video_ocr.run_propainter_inference", new=propainter_ok):
        result = asyncio.run(video_ocr.run_video_ocr(job, settings, vram))

    assert result.success is True
    assert [c["mask_flag"] for c in calls] == ["True"], "only the mask pass should run on success"
    assert os.path.exists(cleaned)


def test_stage_fails_when_propainter_and_all_fallbacks_fail(tmp_path):
    settings, vram, job, cleaned = _setup(tmp_path)

    async def propainter_fails(*a, **k):
        return False

    def failing_subprocess(*args, **kwargs):
        target, mask_flag = args[3], args[4]

        class _P:
            async def wait(self_inner):
                # mask pass succeeds (produces mask.mp4); every non-neural fallback exits non-zero
                if mask_flag == "True":
                    open(target, "w").close()
                    return 0
                return 1

            def kill(self_inner):
                pass

        return _P()

    with patch("asyncio.create_subprocess_exec", side_effect=failing_subprocess), \
         patch("orchestrator.stages.video_ocr.run_propainter_inference", new=propainter_fails):
        result = asyncio.run(video_ocr.run_video_ocr(job, settings, vram))

    assert result.success is False
    assert "fallback" in (result.error or "").lower()
