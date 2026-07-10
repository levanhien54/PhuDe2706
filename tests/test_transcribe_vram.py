"""ASR model default + model-aware VRAM sizing (v2.0)."""
from orchestrator.config import Settings
from orchestrator.stages.transcribe import _whisperx_vram_gb


def test_whisper_default_is_turbo(monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    s = Settings(_env_file=None)
    assert s.whisper_model == "large-v3-turbo"


def test_turbo_reserves_less_vram_than_full():
    assert _whisperx_vram_gb("large-v3-turbo") == 3.0
    assert _whisperx_vram_gb("large-v3") == 5.0
    assert _whisperx_vram_gb("LARGE-V3-TURBO") == 3.0  # case-insensitive
    assert _whisperx_vram_gb("") == 5.0                # unknown -> conservative full size
