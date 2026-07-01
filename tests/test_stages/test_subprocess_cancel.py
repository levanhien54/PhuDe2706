"""Regression tests for GPU-subprocess orphan-on-cancel fixes (audit HIGH #2 & #3).

When a job is cancelled mid-inference, LatentSync / ProPainter subprocesses (each ~8GB VRAM)
must be killed rather than orphaned. These tests inject a fake process whose communicate()
raises CancelledError and assert the child is kill()+wait()'d before the cancel propagates."""
import asyncio
import types
from unittest.mock import patch

import pytest

from orchestrator.stages import latentsync_client, propainter_client


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
