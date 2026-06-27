import pytest
import os


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Reset env vars before each test."""
    monkeypatch.delenv("VRAM_PROFILE", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
