"""Serving config knobs: NEO CPU offload + kvcached (v2.0 decision #4)."""
from orchestrator.config import Settings


def test_cpu_offload_and_kvcached_defaults(monkeypatch):
    for k in ("ENABLE_CPU_OFFLOAD", "CPU_OFFLOAD_GB", "ENABLE_KVCACHED"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.enable_cpu_offload is False
    assert s.cpu_offload_gb == 4
    assert s.enable_kvcached is False


def test_cpu_offload_gb_overridable(monkeypatch):
    monkeypatch.setenv("CPU_OFFLOAD_GB", "10")
    assert Settings(_env_file=None).cpu_offload_gb == 10
