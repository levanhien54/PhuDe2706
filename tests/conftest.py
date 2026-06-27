import sys
import types
import pytest
import os

# Stub heavy ML packages not available in test environment
_STUBS = ["pyrubberband", "librosa", "paddleocr", "paddle", "cv2"]
for _mod in _STUBS:
    if _mod not in sys.modules:
        stub = types.ModuleType(_mod)
        sys.modules[_mod] = stub
        if _mod == "paddleocr":
            stub.PaddleOCR = type("PaddleOCR", (), {})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Reset env vars before each test."""
    monkeypatch.delenv("VRAM_PROFILE", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
