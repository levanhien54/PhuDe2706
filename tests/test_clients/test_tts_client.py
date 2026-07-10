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


def test_tts_engine_router_is_case_insensitive():
    # A capitalized engine value must resolve, not fall through to the gpt_sovits default.
    settings = Settings(tts_engine="OmniVoice", omnivoice_api="http://omnivoice-test:3900",
                        _env_file=None)
    client = TTSClient(settings)
    assert client.engine == "omnivoice"
    assert client.base_url == "http://omnivoice-test:3900"


def test_tts_engine_router_rejects_unknown():
    # An unrecognized engine must fail loudly instead of silently dubbing with the wrong backend.
    settings = Settings(tts_engine="bogus_engine", _env_file=None)
    with pytest.raises(ValueError):
        TTSClient(settings)
