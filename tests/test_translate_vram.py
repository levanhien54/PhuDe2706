"""Quantization-aware LLM VRAM sizing (v2.0 vLLM/AWQ path)."""
from orchestrator.config import Settings
from orchestrator.stages.translate import _llm_vram_gb


def _settings(**kw):
    kw.setdefault("_env_file", None)
    return Settings(**kw)


def test_ollama_reserves_full_vram():
    # Ollama's own Q4 build still needs the full budget regardless of the quantization knob.
    assert _llm_vram_gb(_settings(llm_backend="ollama")) == 9.0
    assert _llm_vram_gb(_settings(llm_backend="ollama", llm_quantization="awq")) == 9.0


def test_vllm_quantized_halves_vram():
    assert _llm_vram_gb(_settings(llm_backend="vllm", llm_quantization="awq")) == 4.5
    assert _llm_vram_gb(_settings(llm_backend="vllm", llm_quantization="fp8")) == 4.5


def test_vllm_full_precision_reserves_full_vram():
    assert _llm_vram_gb(_settings(llm_backend="vllm", llm_quantization="")) == 9.0
