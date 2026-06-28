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
