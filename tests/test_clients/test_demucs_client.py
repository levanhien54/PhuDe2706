import pytest
import respx
import httpx
from orchestrator.clients.demucs_client import DemucsClient
from orchestrator.config import Settings


@pytest.fixture
def settings():
    return Settings(demucs_api="http://demucs-test:8000", http_retries=1, http_timeout=5.0)


@pytest.fixture
def tmp_video(tmp_path):
    f = tmp_path / "test.mp4"
    f.write_bytes(b"fake_video_content")
    return str(f)


@pytest.mark.asyncio
async def test_separate_returns_paths(settings, tmp_video, tmp_path):
    with respx.mock:
        respx.post("http://demucs-test:8000/separate").mock(
            return_value=httpx.Response(200, json={
                "vocal": "/data/temp/test_vocal.wav",
                "background": "/data/temp/test_bg.wav"
            })
        )
        client = DemucsClient(settings)
        result = await client.separate(tmp_video, str(tmp_path))
        assert "vocal" in result
        assert "background" in result
