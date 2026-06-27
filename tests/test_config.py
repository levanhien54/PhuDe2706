import pytest
from orchestrator.config import Settings


def test_default_settings():
    s = Settings()
    assert s.tts_engine == "omnivoice"
    assert s.vram_profile == "16gb"
    assert s.ollama_host == "http://ollama:11434"
    assert s.llm_model == "qwen2.5:14b"


def test_vram_profile_override(monkeypatch):
    monkeypatch.setenv("VRAM_PROFILE", "24gb")
    s = Settings()
    assert s.vram_profile == "24gb"


def test_llm_backend_vllm(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    monkeypatch.setenv("VLLM_HOST", "http://vllm:8080")
    s = Settings()
    assert s.llm_backend == "vllm"
    assert s.vllm_host == "http://vllm:8080"
