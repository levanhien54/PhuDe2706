"""Regression tests for GPU-subprocess orphan-on-cancel + no-timeout fixes.

When a job is cancelled mid-inference, LatentSync / MuseTalk / ProPainter / BS-Roformer / Demucs
subprocesses (each several GB of VRAM) must be killed rather than orphaned (audit HIGH #2/#3, C9).
And a wedged child that never returns must be killed on a timeout ceiling rather than hanging the
worker forever (finding 0.9). These tests inject a fake process whose communicate() either raises
CancelledError or never returns, and assert the child is kill()+wait()'d."""
import asyncio
import types
from unittest.mock import patch

import pytest

from orchestrator.stages import latentsync_client, musetalk_client, propainter_client
from orchestrator.clients import bs_roformer_client, demucs_client
from orchestrator.clients.base import ServiceUnavailableError


class _FakeProc:
    """Stand-in async subprocess whose communicate() is cancelled mid-flight."""

    def __init__(self):
        self.killed = False
        self.waited = False
        self.returncode = None

    async def communicate(self):
        raise asyncio.CancelledError()

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        self.returncode = -9
        return self.returncode


class _HangProc(_FakeProc):
    """Stand-in async subprocess whose communicate() never returns (wedged child)."""

    async def communicate(self):
        await asyncio.Event().wait()  # blocks until cancelled by the timeout


def _fake_create_returning(proc):
    async def _create(*args, **kwargs):
        return proc
    return _create


def test_latentsync_kills_subprocess_on_cancel():
    proc = _FakeProc()
    settings = types.SimpleNamespace(data_dir="data")
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)), \
         patch("orchestrator.stages.latentsync_client.os.path.exists", return_value=True):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                latentsync_client.run_latentsync_inference("v.mp4", "a.wav", "o.mp4", settings)
            )
    assert proc.killed, "LatentSync child was not killed on cancel (orphaned VRAM)"
    assert proc.waited, "LatentSync child was not awaited after kill (zombie)"


def test_propainter_kills_subprocess_on_cancel():
    proc = _FakeProc()
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)), \
         patch("orchestrator.stages.propainter_client.os.path.exists", return_value=True), \
         patch("orchestrator.stages.propainter_client.os.makedirs", return_value=None):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                propainter_client.run_propainter_inference("v.mp4", "m.mp4", "o.mp4", "prop_dir")
            )
    assert proc.killed, "ProPainter child was not killed on cancel (orphaned VRAM)"
    assert proc.waited, "ProPainter child was not awaited after kill (zombie)"


def _musetalk_ctx(tmp_path):
    """Build a MuseTalk call context on a real tmp dir so the temp inference YAML is really written."""
    (tmp_path / "models" / "musetalk").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "out").mkdir()
    settings = types.SimpleNamespace(data_dir=str(tmp_path / "data"))
    output_path = str(tmp_path / "out" / "lipsync.mp4")
    return settings, output_path


def test_musetalk_kills_subprocess_on_cancel_and_cleans_yaml(tmp_path):
    # C9: cover the MuseTalk cancel guard AND assert the stray inference .yaml is removed.
    proc = _FakeProc()
    settings, output_path = _musetalk_ctx(tmp_path)
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                musetalk_client.run_musetalk_inference("v.mp4", "a.wav", output_path, settings)
            )
    assert proc.killed, "MuseTalk child was not killed on cancel (orphaned VRAM)"
    assert proc.waited, "MuseTalk child was not awaited after kill (zombie)"
    leftovers = list((tmp_path / "out").glob("*.yaml"))
    assert leftovers == [], f"MuseTalk left a stray inference yaml behind: {leftovers}"


def test_bsroformer_kills_subprocess_on_cancel(tmp_path):
    # C9: cover the BS-Roformer cancel guard.
    proc = _FakeProc()
    settings = types.SimpleNamespace(separation_model="model.ckpt")
    client = bs_roformer_client.BSRoformerClient(settings)
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(client.separate("v.mp4", str(tmp_path / "sep")))
    assert proc.killed, "BS-Roformer child was not killed on cancel (orphaned VRAM)"
    assert proc.waited, "BS-Roformer child was not awaited after kill (zombie)"


# --- Finding 0.9: wedged child must be killed on the timeout ceiling, not hang forever ---

def test_latentsync_times_out_and_kills(monkeypatch):
    monkeypatch.setenv("GPU_SUBPROCESS_TIMEOUT_SEC", "0.05")
    proc = _HangProc()
    settings = types.SimpleNamespace(data_dir="data")
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)), \
         patch("orchestrator.stages.latentsync_client.os.path.exists", return_value=True):
        with pytest.raises(RuntimeError):
            asyncio.run(
                latentsync_client.run_latentsync_inference("v.mp4", "a.wav", "o.mp4", settings)
            )
    assert proc.killed and proc.waited, "LatentSync did not kill the wedged child on timeout"


def test_musetalk_times_out_and_kills(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_SUBPROCESS_TIMEOUT_SEC", "0.05")
    proc = _HangProc()
    settings, output_path = _musetalk_ctx(tmp_path)
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        with pytest.raises(RuntimeError):
            asyncio.run(
                musetalk_client.run_musetalk_inference("v.mp4", "a.wav", output_path, settings)
            )
    assert proc.killed and proc.waited, "MuseTalk did not kill the wedged child on timeout"
    assert list((tmp_path / "out").glob("*.yaml")) == [], "MuseTalk left a stray yaml after timeout"


def test_propainter_times_out_and_kills(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_SUBPROCESS_TIMEOUT_SEC", "0.05")
    proc = _HangProc()
    prop_dir = tmp_path / "propainter"
    prop_dir.mkdir()
    (prop_dir / "inference_propainter.py").write_text("x")
    output_path = str(tmp_path / "temp" / "cleaned.mp4")
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        ok = asyncio.run(
            propainter_client.run_propainter_inference("v.mp4", "m.mp4", output_path, str(prop_dir))
        )
    assert ok is False, "ProPainter should report failure on timeout"
    assert proc.killed and proc.waited, "ProPainter did not kill the wedged child on timeout"


def test_bsroformer_times_out_and_kills(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_SUBPROCESS_TIMEOUT_SEC", "0.05")
    proc = _HangProc()
    settings = types.SimpleNamespace(separation_model="model.ckpt")
    client = bs_roformer_client.BSRoformerClient(settings)
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        with pytest.raises(RuntimeError):
            asyncio.run(client.separate("v.mp4", str(tmp_path / "sep")))
    assert proc.killed and proc.waited, "BS-Roformer did not kill the wedged child on timeout"


def test_demucs_local_times_out_and_kills(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_SUBPROCESS_TIMEOUT_SEC", "0.05")
    proc = _HangProc()
    settings = types.SimpleNamespace(demucs_api="local")
    client = demucs_client.DemucsClient(settings)
    with patch("asyncio.create_subprocess_exec", _fake_create_returning(proc)):
        with pytest.raises(ServiceUnavailableError):
            asyncio.run(client.separate("v.mp4", str(tmp_path / "sep")))
    assert proc.killed and proc.waited, "Demucs did not kill the wedged child on timeout"
