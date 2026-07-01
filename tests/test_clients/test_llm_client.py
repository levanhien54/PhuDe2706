import pytest
import respx
import httpx
from orchestrator.clients.llm_client import LLMClient
from orchestrator.models import SrtSegment
from orchestrator.config import Settings


@pytest.fixture
def settings_ollama():
    return Settings(llm_backend="ollama", ollama_host="http://ollama-test:11434",
                    llm_model="qwen2.5:14b", http_retries=1, http_timeout=5.0)


@pytest.mark.asyncio
async def test_translate_batch_ollama(settings_ollama):
    segments = [SrtSegment(start=0.0, end=2.0, text="Hello world")]
    with respx.mock:
        respx.post("http://ollama-test:11434/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": '[{"id": 0, "translated": "Xin chào thế giới"}]'}})
        )
        client = LLMClient(settings_ollama)
        result = await client.translate_batch(segments, target_lang="vi")
        assert result[0].translated == "Xin chào thế giới"
        assert result[0].start == 0.0


@pytest.mark.asyncio
async def test_translate_one_handles_bare_string_array(settings_ollama):
    # A backend without an enforced schema may return a JSON array of bare strings instead
    # of objects. _translate_one must fall back to the source text, not raise AttributeError
    # (which previously escaped and aborted the whole translate stage).
    with respx.mock:
        respx.post("http://ollama-test:11434/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": '["xin chào"]'}})
        )
        client = LLMClient(settings_ollama)
        out = await client._translate_one("Hello world", target_lang="vi")
        assert out == "Hello world"
