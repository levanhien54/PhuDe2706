"""WSOLA time-stretch option (v2.0). Verifies TIMESTRETCH_ALGO=wsola routes through audiotsm.

Injects a fake audiotsm so no real dependency is needed; uses a real WAV via soundfile."""
import sys
import types

import numpy as np
import soundfile as sf

from orchestrator import audio_sync


def _install_fake_audiotsm(monkeypatch, calls):
    audiotsm = types.ModuleType("audiotsm")
    io_mod = types.ModuleType("audiotsm.io")
    array_mod = types.ModuleType("audiotsm.io.array")

    class ArrayReader:
        def __init__(self, data):
            self.data = data

    class ArrayWriter:
        def __init__(self, channels):
            self.channels = channels
            self.data = None

    class _TSM:
        def run(self, reader, writer):
            calls.append("run")
            writer.data = reader.data  # passthrough (we only assert the branch is taken)

    def wsola(channels, speed=1.0):
        calls.append(("wsola", channels, speed))
        return _TSM()

    array_mod.ArrayReader = ArrayReader
    array_mod.ArrayWriter = ArrayWriter
    audiotsm.wsola = wsola
    audiotsm.io = io_mod
    io_mod.array = array_mod
    monkeypatch.setitem(sys.modules, "audiotsm", audiotsm)
    monkeypatch.setitem(sys.modules, "audiotsm.io", io_mod)
    monkeypatch.setitem(sys.modules, "audiotsm.io.array", array_mod)


def test_wsola_branch_taken_when_selected(tmp_path, monkeypatch):
    calls = []
    _install_fake_audiotsm(monkeypatch, calls)
    monkeypatch.setenv("TIMESTRETCH_ALGO", "wsola")

    sr = 16000
    y = (0.1 * np.sin(np.linspace(0, 2 * np.pi * 220, sr))).astype("float32")  # ~1s tone
    inp = tmp_path / "in.wav"
    out = tmp_path / "out.wav"
    sf.write(str(inp), y, sr)

    audio_sync.stretch_audio(str(inp), str(out), target_duration=0.5)

    assert out.exists(), "WSOLA path did not write output"
    assert any(isinstance(c, tuple) and c[0] == "wsola" for c in calls), "WSOLA (audiotsm) not invoked"
