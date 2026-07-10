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
async def test_translate_batch_reindexes_when_model_returns_1based_ids(settings_ollama):
    # The model renumbered the batch 1-based. Trusting its ids would map id=1's text to segment
    # index 1, shifting every line by one. The validation must fall back to positional order so
    # each translation lands on its own segment (finding C6).
    segments = [
        SrtSegment(start=0.0, end=2.0, text="Alpha"),
        SrtSegment(start=2.0, end=4.0, text="Bravo"),
    ]
    body = {"message": {"content": '[{"id": 1, "translated": "Một"}, {"id": 2, "translated": "Hai"}]'}}
    with respx.mock:
        respx.post("http://ollama-test:11434/api/chat").mock(return_value=httpx.Response(200, json=body))
        client = LLMClient(settings_ollama)
        result = await client.translate_batch(segments, target_lang="vi")
    assert result[0].translated == "Một"
    assert result[1].translated == "Hai"


def test_llm_backend_router_is_case_insensitive():
    settings = Settings(llm_backend="Ollama", ollama_host="http://ollama-test:11434",
                        llm_model="qwen2.5:14b", _env_file=None)
    client = LLMClient(settings)
    assert client.backend == "ollama"
    assert client.base_url == "http://ollama-test:11434"


def test_llm_backend_router_rejects_unknown():
    with pytest.raises(ValueError):
        LLMClient(Settings(llm_backend="bogus_backend", _env_file=None))


@pytest.mark.asyncio
async def test_ollama_payload_sets_num_ctx_and_temperature(settings_ollama):
    # Ollama defaults to num_ctx=2048; a 20-segment batch prompt (long system prompt + JSON)
    # overflows that, gets truncated, and collapses the fast batched path into slow per-item
    # fallbacks. The payload must raise num_ctx and pin a low temperature for stable JSON.
    import json as _json
    segments = [SrtSegment(start=0.0, end=2.0, text="Hello world")]
    with respx.mock:
        route = respx.post("http://ollama-test:11434/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": '[{"id": 0, "translated": "Xin chào"}]'}})
        )
        client = LLMClient(settings_ollama)
        await client.translate_batch(segments, target_lang="vi")
        body = _json.loads(route.calls.last.request.content)
        assert body["options"]["num_ctx"] == 8192
        assert body["options"]["temperature"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_cjk_leak_repaired_by_retranslate(settings_ollama):
    # qwen (Chinese-origin) may leak Han chars into Vietnamese. The batch result is repaired by
    # a follow-up _translate_one; a clean repair replaces the leaked line rather than stripping.
    segments = [SrtSegment(start=0.0, end=2.0, text="Hello")]
    responses = [
        httpx.Response(200, json={"message": {"content": '[{"id": 0, "translated": "你好 xin chào"}]'}}),
        httpx.Response(200, json={"message": {"content": '[{"id": 0, "translated": "Xin chào"}]'}}),
    ]
    with respx.mock:
        respx.post("http://ollama-test:11434/api/chat").mock(side_effect=responses)
        client = LLMClient(settings_ollama)
        result = await client.translate_batch(segments, target_lang="vi")
    assert result[0].translated == "Xin chào"


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
