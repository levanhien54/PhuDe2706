import pytest
import respx
import httpx
from orchestrator.clients.whisperx_client import WhisperXClient
from orchestrator.config import Settings


@pytest.fixture
def settings():
    return Settings(whisperx_api="http://whisperx-test:8000", http_retries=1, http_timeout=5.0)


@pytest.fixture
def tmp_audio(tmp_path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"fake_audio_content")
    return str(f)


@pytest.mark.asyncio
async def test_transcribe_returns_segments(settings, tmp_audio):
    with respx.mock:
        respx.post("http://whisperx-test:8000/transcribe").mock(
            return_value=httpx.Response(200, json={
                "segments": [{"start": 0.0, "end": 2.0, "text": "Hello"}]
            })
        )
        client = WhisperXClient(settings)
        result = await client.transcribe(tmp_audio)
        assert len(result) == 1
        assert result[0].start == 0.0
        assert result[0].end == 2.0
        assert result[0].text == "Hello"
