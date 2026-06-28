import pytest, respx, httpx
from orchestrator.stages.translate import run_translate
from orchestrator.models import SrtSegment, PipelineJob
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from datetime import datetime


@pytest.fixture
def job():
    return PipelineJob(
        job_id="test-001",
        filename="sample.mp4",
        base_name="sample",
        vram_profile="16gb",
        created_at=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_run_translate_success(job):
    settings = Settings(
        llm_backend="ollama",
        ollama_host="http://ollama-test:11434",
        llm_model="qwen2.5:14b",
        http_retries=1,
        http_timeout=5.0,
    )
    vram = VRAMManager(settings)
    segments = [
        SrtSegment(start=0.0, end=2.0, text="Hello world"),
        SrtSegment(start=3.0, end=5.0, text="Good morning"),
    ]
    with respx.mock:
        respx.post("http://ollama-test:11434/api/generate").mock(
            return_value=httpx.Response(200, json={"response": '[{"id": 0, "translated": "Xin chào thế giới"}, {"id": 1, "translated": "Chào buổi sáng"}]'})
        )
        result, translated = await run_translate(job, segments, settings, vram)
    assert result.success is True
    assert translated[0].translated == "Xin chào thế giới"
    assert translated[1].translated == "Chào buổi sáng"
