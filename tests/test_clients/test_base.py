import pytest
import respx
import httpx
from orchestrator.clients.base import BaseClient, ServiceUnavailableError
from orchestrator.config import Settings


@pytest.fixture
def settings():
    return Settings(http_retries=2, http_timeout=5.0)


@pytest.mark.asyncio
async def test_health_check_success(settings):
    with respx.mock:
        respx.get("http://test-service/health").mock(return_value=httpx.Response(200))
        client = BaseClient("http://test-service", settings)
        assert await client.health_check() is True


@pytest.mark.asyncio
async def test_health_check_failure(settings):
    with respx.mock:
        respx.get("http://test-service/health").mock(return_value=httpx.Response(503))
        client = BaseClient("http://test-service", settings)
        assert await client.health_check() is False


@pytest.mark.asyncio
async def test_post_json_retries_on_500(settings):
    with respx.mock:
        route = respx.post("http://test-service/api").mock(
            side_effect=[
                httpx.Response(500, json={"error": "server error"}),
                httpx.Response(200, json={"result": "ok"}),
            ]
        )
        client = BaseClient("http://test-service", settings)
        result = await client.post_json("/api", {"key": "value"})
        assert result == {"result": "ok"}
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_post_json_retries_on_remote_protocol_error(settings):
    # A mid-response disconnect surfaces as RemoteProtocolError. It's transient, so the retry
    # policy must recover from it instead of aborting the whole request (finding 1.11).
    with respx.mock:
        route = respx.post("http://test-service/api").mock(
            side_effect=[
                httpx.RemoteProtocolError("peer closed connection"),
                httpx.Response(200, json={"result": "ok"}),
            ]
        )
        client = BaseClient("http://test-service", settings)
        result = await client.post_json("/api", {"key": "value"})
        assert result == {"result": "ok"}
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_retry_skips_sleep_after_final_attempt(settings, monkeypatch):
    # Backoff must not sleep after the last (doomed) attempt — that delay is pure waste since we
    # raise immediately afterwards (finding C8). With http_retries=2 there is exactly one gap.
    sleeps = []

    async def _fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("orchestrator.clients.base.asyncio.sleep", _fake_sleep)
    with respx.mock:
        respx.post("http://test-service/api").mock(return_value=httpx.Response(500, json={"e": "x"}))
        client = BaseClient("http://test-service", settings)
        with pytest.raises(ServiceUnavailableError):
            await client.post_json("/api", {"key": "value"})
    assert len(sleeps) == settings.http_retries - 1
