import pytest
import respx
import httpx
from orchestrator.clients.base import BaseClient
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
