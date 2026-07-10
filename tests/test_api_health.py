import asyncio
import httpx
import respx
from orchestrator import api


def _reset_cache():
    api._HEALTH_CACHE.update(ts=0.0, data=None)


def test_api_health_all_up(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: None)
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200, json={}))
        data = asyncio.run(api.api_health())
    assert data["services"]["orchestrator"] == "up"
    assert data["services"]["whisperx"] == "up"
    assert data["services"]["omnivoice"] == "up"
    assert data["services"]["ollama"] == "up"
    assert data["ready"] == data["total"] == 4
    assert data["gpu"] is None


def test_api_health_reports_down(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: None)
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(side_effect=httpx.ConnectError("x"))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200))
        data = asyncio.run(api.api_health())
    assert data["services"]["whisperx"] == "down"
    assert data["ready"] < data["total"]


def test_api_health_gpu_info(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: {"name": "RTX 4090", "vram_used_mb": 1000, "vram_total_mb": 24564})
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200))
        data = asyncio.run(api.api_health())
    assert data["gpu"]["vram_total_mb"] == 24564
