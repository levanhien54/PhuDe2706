import pytest
import respx
import httpx
from orchestrator.clients.tts_client import TTSClient
from orchestrator.config import Settings


@pytest.fixture
def settings_omnivoice():
    return Settings(tts_engine="omnivoice", omnivoice_api="http://omnivoice-test:3900",
                    http_retries=1, http_timeout=5.0)


@pytest.mark.asyncio
async def test_synthesize_omnivoice(settings_omnivoice):
    with respx.mock:
        respx.post("http://omnivoice-test:3900/v1/audio/speech").mock(
            return_value=httpx.Response(200, json={"output_path": "/tmp/out.wav"})
        )
        client = TTSClient(settings_omnivoice)
        result = await client.synthesize(
            text="Xin chào",
            reference_audio="/ref/voice.wav",
            output_path="/tmp/out.wav",
            target_duration=2.0,
        )
        assert result == "/tmp/out.wav"
