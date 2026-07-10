"""ProPainter HD/OOM-mitigation flags are threaded into the inference command (v2.0).

Mocks the subprocess so no GPU/weights are needed; asserts fp16/resize_ratio/subvideo_length
reach the ProPainter CLI."""
import asyncio
from unittest.mock import patch

from orchestrator.stages.propainter_client import run_propainter_inference


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return (b"", b"")

    def kill(self):  # pragma: no cover
        pass

    async def wait(self):  # pragma: no cover
        return 0


def _prep(tmp_path):
    prop_dir = tmp_path / "propainter"
    prop_dir.mkdir()
    (prop_dir / "inference_propainter.py").write_text("x")
    out_parent = tmp_path / "temp"
    out_parent.mkdir()
    tod = out_parent / "propainter_out"  # where the client looks for produced output
    tod.mkdir()
    (tod / "result.mp4").write_text("v")
    return str(prop_dir), str(out_parent / "cleaned.mp4")


def _run(prop_dir, output_path, **kw):
    captured = {}

    def fake_create(*args, **kwargs):
        captured["cmd"] = list(args)
        return _FakeProc()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create):
        ok = asyncio.run(run_propainter_inference("v.mp4", "m.mp4", output_path, prop_dir, **kw))
    return ok, captured["cmd"]


def test_hd_flags_present(tmp_path):
    prop_dir, output_path = _prep(tmp_path)
    ok, cmd = _run(prop_dir, output_path, fp16=True, resize_ratio=0.5, subvideo_length=40)
    assert ok is True
    assert "--fp16" in cmd
    assert "--resize_ratio" in cmd and "0.5" in cmd
    assert "--subvideo_length" in cmd and "40" in cmd


def test_fp16_omitted_when_disabled(tmp_path):
    prop_dir, output_path = _prep(tmp_path)
    ok, cmd = _run(prop_dir, output_path, fp16=False, resize_ratio=1.0, subvideo_length=80)
    assert ok is True
    assert "--fp16" not in cmd
