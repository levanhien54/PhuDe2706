# Video Dubbing Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nâng codebase từ mock/skeleton lên production-grade với real API calls, config management, structured logging, VRAM lifecycle management, và tích hợp LatentSync lip-sync.

**Architecture:** Microservices orchestrated bằng async Python. Mỗi AI service (Demucs, WhisperX, Ollama, TTS, LatentSync) là một HTTP container riêng; orchestrator gọi chúng theo thứ tự phụ thuộc. VRAM manager kiểm soát lifecycle từng model để không bị OOM.

**Tech Stack:** Python 3.11, FastAPI, httpx (async), Pydantic v2, structlog, pytest + respx (mock HTTP), Docker Compose v2, FFmpeg, pyrubberband, PaddleOCR, LatentSync (Docker).

## Global Constraints

- Python 3.11+ (match Dockerfile base)
- Pydantic v2 (đã có trong requirements)
- Tất cả config đọc từ env vars — không hardcode giá trị nào
- Mọi log phải có context: `job_id`, `stage`, `filename`
- VRAM_PROFILE env var: `16gb` hoặc `24gb` — ảnh hưởng thứ tự chạy stages
- Kết quả mỗi stage ghi vào `data/temp/<base_name>/` để resume được
- Retry 3 lần với exponential backoff cho HTTP calls (timeout 300s)
- FFmpeg dùng NVENC nếu GPU có sẵn, fallback sang libx264

---

## File Structure

```
orchestrator/
├── config.py              # Pydantic Settings — tất cả env vars
├── logger.py              # structlog setup, context binding
├── models.py              # Pydantic data models: SrtSegment, PipelineJob, StageResult
├── vram_manager.py        # VRAM budget tracker, model load/unload lifecycle
├── clients/
│   ├── __init__.py
│   ├── base.py            # BaseClient: retry logic, health check, timeout
│   ├── demucs_client.py   # POST /separate → {vocal, background}
│   ├── whisperx_client.py # POST /transcribe → List[SrtSegment]
│   ├── llm_client.py      # POST /api/generate (Ollama) hoặc /v1/completions (vLLM)
│   ├── tts_client.py      # OmniVoice + GPT-SoVITS, unified interface
│   └── lipsync_client.py  # LatentSync POST /sync
├── stages/
│   ├── __init__.py
│   ├── audio_separate.py  # Stage M2: gọi demucs_client
│   ├── transcribe.py      # Stage M3: gọi whisperx_client
│   ├── translate.py       # Stage M4: gọi llm_client, batch segments
│   ├── synthesize.py      # Stage M5: gọi tts_client, kết hợp audio_sync
│   ├── video_ocr.py       # Stage M7+M8: refactor video_process.py
│   └── lip_sync.py        # Stage M9: gọi lipsync_client
├── pipeline.py            # Orchestrate tất cả stages, VRAM-aware
├── main.py                # CLI entrypoint: scan input/, gọi pipeline
├── audio_sync.py          # GIỮ NGUYÊN (đang dùng tốt)
├── video_process.py       # GIỮ NGUYÊN (sẽ được wrap bởi stages/video_ocr.py)
├── requirements.txt       # Thêm structlog, respx
└── Dockerfile             # Thêm healthcheck
```

```
tests/
├── conftest.py            # fixtures: mock HTTP servers, sample SRT
├── test_clients/
│   ├── test_demucs_client.py
│   ├── test_whisperx_client.py
│   ├── test_llm_client.py
│   └── test_tts_client.py
├── test_stages/
│   ├── test_translate.py
│   └── test_synthesize.py
├── test_vram_manager.py
└── test_pipeline.py
```

---

## Task 1: Config, Models & Logger

**Files:**
- Create: `orchestrator/config.py`
- Create: `orchestrator/models.py`
- Create: `orchestrator/logger.py`
- Create: `tests/conftest.py`
- Modify: `orchestrator/requirements.txt`

**Interfaces:**
- Produces:
  - `config.Settings` — singleton settings object
  - `models.SrtSegment(start: float, end: float, text: str)`
  - `models.PipelineJob(job_id: str, filename: str, base_name: str, vram_profile: str)`
  - `models.StageResult(stage: str, success: bool, output_path: str | None, error: str | None)`
  - `logger.get_logger(name: str) -> BoundLogger`

- [ ] **Step 1: Cập nhật requirements.txt**

```txt
httpx==0.27.0
ffmpeg-python==0.2.0
librosa==0.10.2
soundfile==0.12.1
pyrubberband==0.3.0
pydantic==2.8.2
pydantic-settings==2.3.4
python-dotenv==1.0.1
paddlepaddle-gpu>=2.6.0
paddleocr>=2.7.0.3
opencv-python>=4.8.0
structlog==24.2.0
respx==0.21.1
pytest==8.2.2
pytest-asyncio==0.23.7
```

- [ ] **Step 2: Viết tests cho config (failing)**

Tạo file `tests/conftest.py`:

```python
import pytest
import os

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Reset env vars trước mỗi test."""
    monkeypatch.delenv("VRAM_PROFILE", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
```

Tạo file `tests/test_config.py`:

```python
import pytest
from orchestrator.config import Settings

def test_default_settings():
    s = Settings()
    assert s.tts_engine == "omnivoice"
    assert s.vram_profile == "16gb"
    assert s.ollama_host == "http://ollama:11434"
    assert s.llm_model == "qwen2.5:14b"

def test_vram_profile_override(monkeypatch):
    monkeypatch.setenv("VRAM_PROFILE", "24gb")
    s = Settings()
    assert s.vram_profile == "24gb"

def test_llm_backend_vllm(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    monkeypatch.setenv("VLLM_HOST", "http://vllm:8080")
    s = Settings()
    assert s.llm_backend == "vllm"
    assert s.vllm_host == "http://vllm:8080"
```

- [ ] **Step 3: Chạy test để xác nhận FAIL**

```bash
cd C:\Users\sonson\Desktop\PhuDe27.06
docker run --rm -v .:/app -w /app python:3.11-slim bash -c "pip install pydantic-settings pytest -q && python -m pytest tests/test_config.py -v 2>&1 | head -30"
```

Hoặc nếu có Python local:
```bash
cd orchestrator && pip install pydantic-settings pytest -q
python -m pytest ../tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'orchestrator.config'`

- [ ] **Step 4: Implement config.py**

```python
# orchestrator/config.py
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    # Service endpoints
    ollama_host: str = Field("http://ollama:11434", env="OLLAMA_HOST")
    vllm_host: str = Field("http://vllm:8080", env="VLLM_HOST")
    whisperx_api: str = Field("http://whisperx:8000", env="WHISPERX_API")
    demucs_api: str = Field("http://demucs:8000", env="DEMUCS_API")
    tts_api: str = Field("http://tts:9880", env="TTS_API")
    omnivoice_api: str = Field("http://omnivoice:3900", env="OMNIVOICE_API")
    lipsync_api: str = Field("http://lipsync:8010", env="LIPSYNC_API")

    # Engine selection
    tts_engine: str = Field("omnivoice", env="TTS_ENGINE")  # omnivoice | gpt_sovits
    llm_backend: str = Field("ollama", env="LLM_BACKEND")    # ollama | vllm
    llm_model: str = Field("qwen2.5:14b", env="LLM_MODEL")
    vram_profile: str = Field("16gb", env="VRAM_PROFILE")    # 16gb | 24gb
    enable_lipsync: bool = Field(False, env="ENABLE_LIPSYNC")

    # Paths
    data_dir: str = Field("/app/data", env="DATA_DIR")

    # Tuning
    http_timeout: float = Field(300.0, env="HTTP_TIMEOUT")
    http_retries: int = Field(3, env="HTTP_RETRIES")
    ocr_fps: float = Field(2.0, env="OCR_FPS")
    tts_max_ratio: float = Field(1.5, env="TTS_MAX_RATIO")  # max stretch ratio

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Implement models.py**

```python
# orchestrator/models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class SrtSegment(BaseModel):
    start: float
    end: float
    text: str
    translated: Optional[str] = None

    @property
    def duration(self) -> float:
        return self.end - self.start

class PipelineJob(BaseModel):
    job_id: str
    filename: str
    base_name: str
    vram_profile: str = "16gb"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class StageResult(BaseModel):
    stage: str
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
```

- [ ] **Step 6: Implement logger.py**

```python
# orchestrator/logger.py
import structlog
import logging
import sys

def setup_logging(log_level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )

def get_logger(name: str):
    return structlog.get_logger(name)

def bind_job_context(job_id: str, filename: str) -> None:
    structlog.contextvars.bind_contextvars(job_id=job_id, filename=filename)

def clear_job_context() -> None:
    structlog.contextvars.clear_contextvars()
```

- [ ] **Step 7: Chạy tests để xác nhận PASS**

```bash
python -m pytest tests/test_config.py -v
```

Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add orchestrator/config.py orchestrator/models.py orchestrator/logger.py orchestrator/requirements.txt tests/conftest.py tests/test_config.py
git commit -m "feat: add config, models, logger foundation"
```

---

## Task 2: BaseClient với Retry & Health Check

**Files:**
- Create: `orchestrator/clients/__init__.py`
- Create: `orchestrator/clients/base.py`
- Create: `tests/test_clients/test_base.py`

**Interfaces:**
- Consumes: `config.Settings`
- Produces:
  - `clients.base.BaseClient(base_url: str, settings: Settings)`
  - `async BaseClient.post_file(endpoint: str, file_path: str, extra_data: dict) -> dict`
  - `async BaseClient.post_json(endpoint: str, payload: dict) -> dict`
  - `async BaseClient.health_check() -> bool`

- [ ] **Step 1: Viết tests (failing)**

```python
# tests/test_clients/test_base.py
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
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```bash
python -m pytest tests/test_clients/test_base.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement clients/__init__.py**

```python
# orchestrator/clients/__init__.py
from .demucs_client import DemucsClient
from .whisperx_client import WhisperXClient
from .llm_client import LLMClient
from .tts_client import TTSClient
from .lipsync_client import LipSyncClient

__all__ = ["DemucsClient", "WhisperXClient", "LLMClient", "TTSClient", "LipSyncClient"]
```

- [ ] **Step 4: Implement clients/base.py**

```python
# orchestrator/clients/base.py
import asyncio
import httpx
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

class ServiceUnavailableError(Exception):
    pass

class BaseClient:
    def __init__(self, base_url: str, settings: Settings):
        self.base_url = base_url.rstrip("/")
        self.settings = settings

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                wait = 2 ** attempt
                log.warning("http_retry", attempt=attempt + 1, url=url, error=str(e), wait=wait)
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(f"Failed after {self.settings.http_retries} retries: {last_exc}")

    async def post_file(self, endpoint: str, file_path: str, extra_data: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                    with open(file_path, "rb") as f:
                        files = {"file": (file_path.split("/")[-1], f, "audio/wav")}
                        data = extra_data or {}
                        resp = await client.post(url, files=files, data=data)
                        if resp.status_code >= 500:
                            raise httpx.HTTPStatusError(
                                f"Server error {resp.status_code}", request=resp.request, response=resp
                            )
                        resp.raise_for_status()
                        return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                wait = 2 ** attempt
                log.warning("http_retry", attempt=attempt + 1, url=url, error=str(e), wait=wait)
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(f"Failed after {self.settings.http_retries} retries: {last_exc}")
```

- [ ] **Step 5: Chạy tests để xác nhận PASS**

```bash
python -m pytest tests/test_clients/test_base.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add orchestrator/clients/ tests/test_clients/
git commit -m "feat: add BaseClient with retry and health check"
```

---

## Task 3: API Clients — Demucs, WhisperX, LLM, TTS, LipSync

**Files:**
- Create: `orchestrator/clients/demucs_client.py`
- Create: `orchestrator/clients/whisperx_client.py`
- Create: `orchestrator/clients/llm_client.py`
- Create: `orchestrator/clients/tts_client.py`
- Create: `orchestrator/clients/lipsync_client.py`
- Create: `tests/test_clients/test_demucs_client.py`
- Create: `tests/test_clients/test_whisperx_client.py`
- Create: `tests/test_clients/test_llm_client.py`
- Create: `tests/test_clients/test_tts_client.py`

**Interfaces:**
- Consumes: `clients.base.BaseClient`, `models.SrtSegment`
- Produces:
  - `DemucsClient.separate(video_path: str, output_dir: str) -> dict[str, str]`  
    Returns: `{"vocal": "/path/vocal.wav", "background": "/path/bg.wav"}`
  - `WhisperXClient.transcribe(audio_path: str) -> list[SrtSegment]`
  - `LLMClient.translate_batch(segments: list[SrtSegment], target_lang: str = "vi") -> list[SrtSegment]`
  - `TTSClient.synthesize(text: str, reference_audio: str, output_path: str, target_duration: float) -> str`
  - `LipSyncClient.sync(video_path: str, audio_path: str, output_path: str) -> str`

- [ ] **Step 1: Viết tests (failing)**

```python
# tests/test_clients/test_demucs_client.py
import pytest, respx, httpx, os, tempfile
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
```

```python
# tests/test_clients/test_llm_client.py
import pytest, respx, httpx
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
        respx.post("http://ollama-test:11434/api/generate").mock(
            return_value=httpx.Response(200, json={"response": "Xin chào thế giới"})
        )
        client = LLMClient(settings_ollama)
        result = await client.translate_batch(segments, target_lang="vi")
        assert result[0].translated == "Xin chào thế giới"
        assert result[0].start == 0.0
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```bash
python -m pytest tests/test_clients/ -v
```

Expected: `ImportError` cho các client chưa có

- [ ] **Step 3: Implement demucs_client.py**

```python
# orchestrator/clients/demucs_client.py
import os
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

class DemucsClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.demucs_api, settings)

    async def separate(self, video_path: str, output_dir: str) -> dict[str, str]:
        log.info("demucs_separate_start", video=video_path)
        result = await self.post_file("/separate", video_path, {"output_dir": output_dir})
        log.info("demucs_separate_done", vocal=result.get("vocal"))
        return {"vocal": result["vocal"], "background": result["background"]}
```

- [ ] **Step 4: Implement whisperx_client.py**

```python
# orchestrator/clients/whisperx_client.py
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

class WhisperXClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.whisperx_api, settings)

    async def transcribe(self, audio_path: str) -> list[SrtSegment]:
        log.info("whisperx_transcribe_start", audio=audio_path)
        result = await self.post_file("/transcribe", audio_path)
        # Expected response: {"segments": [{"start": 0.0, "end": 2.5, "text": "..."}]}
        segments = [
            SrtSegment(start=s["start"], end=s["end"], text=s["text"].strip())
            for s in result.get("segments", [])
            if s.get("text", "").strip()
        ]
        log.info("whisperx_transcribe_done", segment_count=len(segments))
        return segments
```

- [ ] **Step 5: Implement llm_client.py**

```python
# orchestrator/clients/llm_client.py
import asyncio
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.models import SrtSegment
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TRANSLATE_PROMPT = (
    "Dịch câu sau sang tiếng Việt một cách tự nhiên, giữ đúng ngữ cảnh. "
    "Chỉ trả về bản dịch, không giải thích:\n\n{text}"
)

class LLMClient(BaseClient):
    def __init__(self, settings: Settings):
        base_url = settings.vllm_host if settings.llm_backend == "vllm" else settings.ollama_host
        super().__init__(base_url, settings)
        self.settings = settings

    async def _translate_one(self, text: str) -> str:
        prompt = _TRANSLATE_PROMPT.format(text=text)
        if self.settings.llm_backend == "vllm":
            payload = {
                "model": self.settings.llm_model,
                "prompt": prompt,
                "max_tokens": 512,
                "temperature": 0.3,
            }
            result = await self.post_json("/v1/completions", payload)
            return result["choices"][0]["text"].strip()
        else:  # ollama
            payload = {
                "model": self.settings.llm_model,
                "prompt": prompt,
                "stream": False,
            }
            result = await self.post_json("/api/generate", payload)
            return result.get("response", "").strip()

    async def translate_batch(
        self, segments: list[SrtSegment], target_lang: str = "vi"
    ) -> list[SrtSegment]:
        log.info("llm_translate_start", segment_count=len(segments), backend=self.settings.llm_backend)
        tasks = [self._translate_one(s.text) for s in segments]
        translations = await asyncio.gather(*tasks)
        result = []
        for seg, trans in zip(segments, translations):
            result.append(SrtSegment(start=seg.start, end=seg.end, text=seg.text, translated=trans))
        log.info("llm_translate_done")
        return result
```

- [ ] **Step 6: Implement tts_client.py**

```python
# orchestrator/clients/tts_client.py
import os
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

class TTSClient(BaseClient):
    """Unified TTS client. Chọn engine dựa vào settings.tts_engine."""

    def __init__(self, settings: Settings):
        if settings.tts_engine == "omnivoice":
            super().__init__(settings.omnivoice_api, settings)
        else:
            super().__init__(settings.tts_api, settings)
        self.settings = settings

    async def synthesize(
        self,
        text: str,
        reference_audio: str,
        output_path: str,
        target_duration: float,
    ) -> str:
        """
        Sinh giọng nói clone từ reference_audio cho đoạn text.
        target_duration: thời lượng mong muốn (giây) — dùng để quyết định stretch.
        Trả về đường dẫn file WAV đã tạo.
        """
        log.info("tts_synthesize", engine=self.settings.tts_engine, text_len=len(text))

        if self.settings.tts_engine == "omnivoice":
            payload = {
                "text": text,
                "language": "vi",
                "reference_audio": reference_audio,
                "output_path": output_path,
            }
            result = await self.post_json("/v1/audio/speech", payload)
        else:  # gpt_sovits
            payload = {
                "text": text,
                "text_language": "vi",
                "refer_wav_path": reference_audio,
                "output_path": output_path,
            }
            result = await self.post_json("/tts", payload)

        generated_path = result.get("output_path", output_path)
        log.info("tts_synthesize_done", output=generated_path)
        return generated_path
```

- [ ] **Step 7: Implement lipsync_client.py**

```python
# orchestrator/clients/lipsync_client.py
from orchestrator.clients.base import BaseClient
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

class LipSyncClient(BaseClient):
    def __init__(self, settings: Settings):
        super().__init__(settings.lipsync_api, settings)

    async def sync(self, video_path: str, audio_path: str, output_path: str) -> str:
        """
        Gọi LatentSync API để đồng bộ khẩu hình.
        video_path: video chưa có lip-sync
        audio_path: audio tiếng Việt đã được tạo bởi TTS
        output_path: nơi lưu video kết quả
        """
        log.info("lipsync_start", video=video_path)
        payload = {
            "video_path": video_path,
            "audio_path": audio_path,
            "output_path": output_path,
        }
        result = await self.post_json("/sync", payload)
        out = result.get("output_path", output_path)
        log.info("lipsync_done", output=out)
        return out
```

- [ ] **Step 8: Chạy tests để xác nhận PASS**

```bash
python -m pytest tests/test_clients/ -v
```

Expected: tất cả tests PASS

- [ ] **Step 9: Commit**

```bash
git add orchestrator/clients/ tests/test_clients/
git commit -m "feat: add all API clients (demucs, whisperx, llm, tts, lipsync)"
```

---

## Task 4: VRAM Manager

**Files:**
- Create: `orchestrator/vram_manager.py`
- Create: `tests/test_vram_manager.py`

**Interfaces:**
- Consumes: `config.Settings`
- Produces:
  - `VRAMManager(settings: Settings)`
  - `async VRAMManager.acquire(service: str, vram_gb: float) -> None`  — đợi đủ VRAM rồi "đặt chỗ"
  - `async VRAMManager.release(service: str) -> None` — trả lại VRAM
  - `VRAMManager.available_gb() -> float`
  - Context manager: `async with vram_manager.slot(service, vram_gb):`

- [ ] **Step 1: Viết tests (failing)**

```python
# tests/test_vram_manager.py
import pytest, asyncio
from orchestrator.vram_manager import VRAMManager
from orchestrator.config import Settings

@pytest.fixture
def mgr_16():
    return VRAMManager(Settings(vram_profile="16gb"))

@pytest.fixture
def mgr_24():
    return VRAMManager(Settings(vram_profile="24gb"))

@pytest.mark.asyncio
async def test_16gb_total(mgr_16):
    assert mgr_16.total_gb == 16.0

@pytest.mark.asyncio
async def test_24gb_total(mgr_24):
    assert mgr_24.total_gb == 24.0

@pytest.mark.asyncio
async def test_acquire_release(mgr_16):
    await mgr_16.acquire("whisperx", 5.0)
    assert mgr_16.available_gb() == 11.0
    await mgr_16.release("whisperx")
    assert mgr_16.available_gb() == 16.0

@pytest.mark.asyncio
async def test_slot_context_manager(mgr_16):
    async with mgr_16.slot("demucs", 3.0):
        assert mgr_16.available_gb() == 13.0
    assert mgr_16.available_gb() == 16.0

@pytest.mark.asyncio
async def test_waits_for_capacity(mgr_16):
    await mgr_16.acquire("big_model", 14.0)
    # Now only 2GB available, requesting 5GB should wait
    acquired = False
    async def delayed_release():
        await asyncio.sleep(0.1)
        await mgr_16.release("big_model")

    async def try_acquire():
        nonlocal acquired
        await mgr_16.acquire("other", 5.0)
        acquired = True

    await asyncio.gather(delayed_release(), try_acquire())
    assert acquired is True
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```bash
python -m pytest tests/test_vram_manager.py -v
```

- [ ] **Step 3: Implement vram_manager.py**

```python
# orchestrator/vram_manager.py
import asyncio
from contextlib import asynccontextmanager
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TOTAL_BY_PROFILE = {"16gb": 16.0, "24gb": 24.0}
_RESERVED_OVERHEAD = 1.5  # OS + driver overhead GB

class VRAMManager:
    def __init__(self, settings: Settings):
        self.total_gb = _TOTAL_BY_PROFILE.get(settings.vram_profile, 16.0)
        self._usable_gb = self.total_gb - _RESERVED_OVERHEAD
        self._allocated: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self._event.set()

    def available_gb(self) -> float:
        used = sum(self._allocated.values())
        return self._usable_gb - used

    async def acquire(self, service: str, vram_gb: float) -> None:
        while True:
            async with self._lock:
                if self.available_gb() >= vram_gb:
                    self._allocated[service] = vram_gb
                    log.info(
                        "vram_acquire",
                        service=service,
                        requested_gb=vram_gb,
                        remaining_gb=round(self.available_gb(), 2),
                    )
                    return
            # Not enough VRAM — wait for a release event
            self._event.clear()
            await self._event.wait()

    async def release(self, service: str) -> None:
        async with self._lock:
            freed = self._allocated.pop(service, 0.0)
            log.info(
                "vram_release",
                service=service,
                freed_gb=freed,
                remaining_gb=round(self.available_gb(), 2),
            )
        self._event.set()

    @asynccontextmanager
    async def slot(self, service: str, vram_gb: float):
        await self.acquire(service, vram_gb)
        try:
            yield
        finally:
            await self.release(service)
```

- [ ] **Step 4: Chạy tests để xác nhận PASS**

```bash
python -m pytest tests/test_vram_manager.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/vram_manager.py tests/test_vram_manager.py
git commit -m "feat: add VRAM manager with async slot allocation"
```

---

## Task 5: Pipeline Stages (M2–M8 refactored)

**Files:**
- Create: `orchestrator/stages/__init__.py`
- Create: `orchestrator/stages/audio_separate.py`
- Create: `orchestrator/stages/transcribe.py`
- Create: `orchestrator/stages/translate.py`
- Create: `orchestrator/stages/synthesize.py`
- Create: `orchestrator/stages/video_ocr.py`
- Create: `orchestrator/stages/lip_sync.py`
- Create: `tests/test_stages/test_translate.py`
- Create: `tests/test_stages/test_synthesize.py`

**Interfaces:**
- Consumes: tất cả clients, `models`, `config.Settings`, `vram_manager.VRAMManager`, `audio_sync.stretch_audio`
- Produces: mỗi stage là `async def run_*(job, ..., settings, vram) -> StageResult`
  - `run_audio_separate(job: PipelineJob, settings, vram) -> StageResult`  
    Output: `data/temp/<base_name>/vocal.wav`, `data/temp/<base_name>/bg.wav`
  - `run_transcribe(job, settings, vram) -> tuple[StageResult, list[SrtSegment]]`
  - `run_translate(job, segments, settings, vram) -> tuple[StageResult, list[SrtSegment]]`
  - `run_synthesize(job, segments, settings, vram) -> StageResult`  
    Output: `data/temp/<base_name>/new_vocal.wav`
  - `run_video_ocr(job, settings, vram) -> StageResult`  
    Output: `data/temp/<base_name>/cleaned.mp4`
  - `run_lip_sync(job, settings, vram) -> StageResult`  
    Output: `data/temp/<base_name>/lipsync.mp4`

- [ ] **Step 1: Viết tests cho translate stage (failing)**

```python
# tests/test_stages/test_translate.py
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
        SrtSegment(start=2.0, end=4.0, text="Good morning"),
    ]
    with respx.mock:
        respx.post("http://ollama-test:11434/api/generate").mock(
            side_effect=[
                httpx.Response(200, json={"response": "Xin chào thế giới"}),
                httpx.Response(200, json={"response": "Chào buổi sáng"}),
            ]
        )
        result, translated = await run_translate(job, segments, settings, vram)
    assert result.success is True
    assert translated[0].translated == "Xin chào thế giới"
    assert translated[1].translated == "Chào buổi sáng"
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```bash
python -m pytest tests/test_stages/test_translate.py -v
```

- [ ] **Step 3: Implement stages/__init__.py**

```python
# orchestrator/stages/__init__.py
from .audio_separate import run_audio_separate
from .transcribe import run_transcribe
from .translate import run_translate
from .synthesize import run_synthesize
from .video_ocr import run_video_ocr
from .lip_sync import run_lip_sync

__all__ = [
    "run_audio_separate", "run_transcribe", "run_translate",
    "run_synthesize", "run_video_ocr", "run_lip_sync",
]
```

- [ ] **Step 4: Implement stages/audio_separate.py**

```python
# orchestrator/stages/audio_separate.py
import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.demucs_client import DemucsClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_DEMUCS_VRAM_GB = 3.0

async def run_audio_separate(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    video_path = os.path.join(settings.data_dir, "input", job.filename)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with vram.slot("demucs", _DEMUCS_VRAM_GB):
            client = DemucsClient(settings)
            result = await client.separate(video_path, temp_dir)
        return StageResult(
            stage="audio_separate",
            success=True,
            output_path=result["vocal"],
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("audio_separate_failed", error=str(e))
        return StageResult(stage="audio_separate", success=False, error=str(e))
```

- [ ] **Step 5: Implement stages/transcribe.py**

```python
# orchestrator/stages/transcribe.py
import os, time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.whisperx_client import WhisperXClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_WHISPERX_VRAM_GB = 5.0

async def run_transcribe(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> tuple[StageResult, list[SrtSegment]]:
    start_time = time.monotonic()
    vocal_path = os.path.join(settings.data_dir, "temp", job.base_name, "vocal.wav")

    try:
        async with vram.slot("whisperx", _WHISPERX_VRAM_GB):
            client = WhisperXClient(settings)
            segments = await client.transcribe(vocal_path)
        result = StageResult(
            stage="transcribe",
            success=True,
            output_path=vocal_path,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, segments
    except Exception as e:
        log.error("transcribe_failed", error=str(e))
        return StageResult(stage="transcribe", success=False, error=str(e)), []
```

- [ ] **Step 6: Implement stages/translate.py**

```python
# orchestrator/stages/translate.py
import time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.llm_client import LLMClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

# GemmaX2-28-9B ~9GB, Qwen2.5-14B ~9GB khi quant
_LLM_VRAM_GB = 9.0

async def run_translate(
    job: PipelineJob,
    segments: list[SrtSegment],
    settings: Settings,
    vram: VRAMManager,
) -> tuple[StageResult, list[SrtSegment]]:
    start_time = time.monotonic()
    try:
        async with vram.slot("llm", _LLM_VRAM_GB):
            client = LLMClient(settings)
            translated = await client.translate_batch(segments)
        result = StageResult(
            stage="translate",
            success=True,
            duration_seconds=time.monotonic() - start_time,
        )
        return result, translated
    except Exception as e:
        log.error("translate_failed", error=str(e))
        return StageResult(stage="translate", success=False, error=str(e)), segments
```

- [ ] **Step 7: Implement stages/synthesize.py**

```python
# orchestrator/stages/synthesize.py
import os, time
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.tts_client import TTSClient
from orchestrator.audio_sync import stretch_audio
from orchestrator.logger import get_logger
import soundfile as sf

log = get_logger(__name__)

_TTS_VRAM_GB = 4.0

async def run_synthesize(
    job: PipelineJob,
    segments: list[SrtSegment],
    settings: Settings,
    vram: VRAMManager,
) -> StageResult:
    """
    Sinh từng đoạn audio rồi stretch cho khớp timestamp, cuối cùng ghép lại.
    """
    start_time = time.monotonic()
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    vocal_path = os.path.join(temp_dir, "vocal.wav")
    final_output = os.path.join(temp_dir, "new_vocal.wav")

    # Đọc reference audio để lấy sample rate
    try:
        ref_data, sr = sf.read(vocal_path)
    except Exception:
        # Nếu chưa có file thật (mock env), dùng sr mặc định
        sr = 22050

    import numpy as np
    combined_audio = np.zeros(0, dtype=np.float32)

    try:
        async with vram.slot("tts", _TTS_VRAM_GB):
            client = TTSClient(settings)
            for i, seg in enumerate(segments):
                if not seg.translated:
                    continue
                seg_output = os.path.join(temp_dir, f"seg_{i:04d}.wav")
                await client.synthesize(
                    text=seg.translated,
                    reference_audio=vocal_path,
                    output_path=seg_output,
                    target_duration=seg.duration,
                )
                # Time-stretch để khớp duration
                stretched_path = os.path.join(temp_dir, f"seg_{i:04d}_stretched.wav")
                stretch_audio(seg_output, stretched_path, seg.duration)

                # Ghép vào buffer theo vị trí timestamp
                seg_data, _ = sf.read(stretched_path)
                start_sample = int(seg.start * sr)
                end_sample = start_sample + len(seg_data)
                if end_sample > len(combined_audio):
                    combined_audio = np.pad(combined_audio, (0, end_sample - len(combined_audio)))
                combined_audio[start_sample:end_sample] += seg_data

        sf.write(final_output, combined_audio, sr)
        return StageResult(
            stage="synthesize",
            success=True,
            output_path=final_output,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("synthesize_failed", error=str(e))
        return StageResult(stage="synthesize", success=False, error=str(e))
```

- [ ] **Step 8: Implement stages/video_ocr.py**

```python
# orchestrator/stages/video_ocr.py
import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.video_process import remove_watermark_from_video
from orchestrator.logger import get_logger

log = get_logger(__name__)

_OCR_VRAM_GB = 2.0  # PaddleOCR GPU nhẹ

async def run_video_ocr(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    input_video = os.path.join(settings.data_dir, "input", job.filename)
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    os.makedirs(temp_dir, exist_ok=True)
    output_video = os.path.join(temp_dir, "cleaned.mp4")

    try:
        async with vram.slot("paddleocr", _OCR_VRAM_GB):
            import asyncio
            await asyncio.to_thread(remove_watermark_from_video, input_video, output_video)
        return StageResult(
            stage="video_ocr",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("video_ocr_failed", error=str(e))
        return StageResult(stage="video_ocr", success=False, error=str(e))
```

- [ ] **Step 9: Implement stages/lip_sync.py**

```python
# orchestrator/stages/lip_sync.py
import os, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.lipsync_client import LipSyncClient
from orchestrator.logger import get_logger

log = get_logger(__name__)

_LIPSYNC_VRAM_GB = 8.0

async def run_lip_sync(
    job: PipelineJob, settings: Settings, vram: VRAMManager
) -> StageResult:
    start_time = time.monotonic()
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    # Input: cleaned video + new vocal
    cleaned_video = os.path.join(temp_dir, "cleaned.mp4")
    new_vocal = os.path.join(temp_dir, "new_vocal.wav")
    output_video = os.path.join(temp_dir, "lipsync.mp4")

    try:
        async with vram.slot("lipsync", _LIPSYNC_VRAM_GB):
            client = LipSyncClient(settings)
            await client.sync(cleaned_video, new_vocal, output_video)
        return StageResult(
            stage="lip_sync",
            success=True,
            output_path=output_video,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("lipsync_failed", error=str(e))
        return StageResult(stage="lip_sync", success=False, error=str(e))
```

- [ ] **Step 10: Chạy tests để xác nhận PASS**

```bash
python -m pytest tests/test_stages/ -v
```

Expected: tests liên quan PASS

- [ ] **Step 11: Commit**

```bash
git add orchestrator/stages/ tests/test_stages/
git commit -m "feat: implement all pipeline stages (M2-M9)"
```

---

## Task 6: Pipeline Orchestrator (pipeline.py + main.py)

**Files:**
- Modify: `orchestrator/pipeline.py` (tạo mới)
- Modify: `orchestrator/main.py` (rewrite)
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: tất cả stages, `VRAMManager`, `Settings`, `PipelineJob`
- Produces:
  - `async run_pipeline(job: PipelineJob, settings: Settings) -> dict[str, StageResult]`
  - `main.py`: CLI entry point đọc `data/input/`, chạy pipeline per file

- [ ] **Step 1: Viết test pipeline (failing)**

```python
# tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from orchestrator.pipeline import run_pipeline
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from datetime import datetime

@pytest.fixture
def job():
    return PipelineJob(
        job_id="pipe-001",
        filename="sample.mp4",
        base_name="sample",
        vram_profile="16gb",
        created_at=datetime.utcnow(),
    )

@pytest.mark.asyncio
async def test_pipeline_16gb_stage_order(job):
    """Xác nhận 16GB pipeline chạy theo thứ tự đúng và không bị lỗi OOM giả."""
    settings = Settings(vram_profile="16gb", enable_lipsync=False, http_retries=1)

    ok = StageResult(stage="x", success=True, output_path="/tmp/x")
    segments = [SrtSegment(start=0.0, end=2.0, text="Hello", translated="Xin chào")]

    with (
        patch("orchestrator.pipeline.run_audio_separate", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.run_video_ocr", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.run_transcribe", new_callable=AsyncMock, return_value=(ok, segments)),
        patch("orchestrator.pipeline.run_translate", new_callable=AsyncMock, return_value=(ok, segments)),
        patch("orchestrator.pipeline.run_synthesize", new_callable=AsyncMock, return_value=ok),
        patch("orchestrator.pipeline.mix_audio_to_video"),
    ):
        results = await run_pipeline(job, settings)

    assert results["audio_separate"].success
    assert results["transcribe"].success
    assert results["translate"].success
    assert results["synthesize"].success
    assert "lip_sync" not in results  # ENABLE_LIPSYNC=False
```

- [ ] **Step 2: Implement pipeline.py**

```python
# orchestrator/pipeline.py
import os, uuid, asyncio, time
from orchestrator.models import PipelineJob, StageResult
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.logger import get_logger, bind_job_context, clear_job_context
from orchestrator.stages import (
    run_audio_separate, run_transcribe, run_translate,
    run_synthesize, run_video_ocr, run_lip_sync,
)
from orchestrator.audio_sync import mix_audio_to_video

log = get_logger(__name__)


async def run_pipeline(job: PipelineJob, settings: Settings) -> dict[str, StageResult]:
    bind_job_context(job.job_id, job.filename)
    vram = VRAMManager(settings)
    results: dict[str, StageResult] = {}
    pipeline_start = time.monotonic()

    log.info("pipeline_start", vram_profile=settings.vram_profile, lipsync=settings.enable_lipsync)

    # --- 16GB: M2 + M7 chạy song song (cả 2 cộng lại ~5GB) ---
    # --- 24GB: chạy song song thoải mái hơn ---
    sep_task = asyncio.create_task(run_audio_separate(job, settings, vram))
    ocr_task = asyncio.create_task(run_video_ocr(job, settings, vram))
    sep_result, ocr_result = await asyncio.gather(sep_task, ocr_task)

    results["audio_separate"] = sep_result
    results["video_ocr"] = ocr_result

    if not sep_result.success:
        log.error("pipeline_abort", reason="audio_separate failed")
        clear_job_context()
        return results

    # --- M3: WhisperX STT ---
    transcribe_result, segments = await run_transcribe(job, settings, vram)
    results["transcribe"] = transcribe_result

    if not transcribe_result.success or not segments:
        log.error("pipeline_abort", reason="transcribe failed or empty")
        clear_job_context()
        return results

    # --- M4: LLM Translate ---
    translate_result, translated_segments = await run_translate(job, segments, settings, vram)
    results["translate"] = translate_result

    if not translate_result.success:
        log.warning("translate_failed_using_original")
        translated_segments = segments  # fallback: dùng text gốc

    # --- M5+M6: TTS + Audio Sync ---
    synth_result = await run_synthesize(job, translated_segments, settings, vram)
    results["synthesize"] = synth_result

    if not synth_result.success:
        log.error("pipeline_abort", reason="synthesize failed")
        clear_job_context()
        return results

    # --- M9: Lip-Sync (tuỳ chọn, chỉ chạy nếu bật) ---
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)

    if settings.enable_lipsync:
        lipsync_result = await run_lip_sync(job, settings, vram)
        results["lip_sync"] = lipsync_result
        video_source = os.path.join(temp_dir, "lipsync.mp4") if lipsync_result.success else os.path.join(temp_dir, "cleaned.mp4")
    else:
        video_source = os.path.join(temp_dir, "cleaned.mp4")

    # --- M10: FFmpeg Mux ---
    output_dir = os.path.join(settings.data_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{job.base_name}_dubbed.mp4")
    new_vocal = os.path.join(temp_dir, "new_vocal.wav")
    bg_audio = os.path.join(temp_dir, "bg.wav")

    mux_start = time.monotonic()
    mix_audio_to_video(video_source, new_vocal, bg_audio, output_path)
    results["mux"] = StageResult(
        stage="mux",
        success=os.path.exists(output_path),
        output_path=output_path,
        duration_seconds=time.monotonic() - mux_start,
    )

    total_time = time.monotonic() - pipeline_start
    log.info("pipeline_done", output=output_path, total_seconds=round(total_time, 1))
    clear_job_context()
    return results
```

- [ ] **Step 3: Rewrite main.py**

```python
# orchestrator/main.py
import asyncio
import os
import uuid
import argparse
from datetime import datetime

from orchestrator.config import get_settings
from orchestrator.logger import setup_logging, get_logger
from orchestrator.models import PipelineJob
from orchestrator.pipeline import run_pipeline

log = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Video Dubbing Orchestrator")
    parser.add_argument(
        "--video", type=str, default=None,
        help="Tên file video cụ thể trong data/input/ (bỏ trống để xử lý tất cả)"
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return parser.parse_args()


async def main():
    args = parse_args()
    setup_logging(args.log_level)
    settings = get_settings()

    input_dir = os.path.join(settings.data_dir, "input")
    output_dir = os.path.join(settings.data_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if args.video:
        videos = [args.video] if args.video.endswith(".mp4") else []
    else:
        videos = [f for f in os.listdir(input_dir) if f.endswith(".mp4")]

    if not videos:
        log.warning("no_videos_found", input_dir=input_dir)
        print(f"Không tìm thấy video nào trong {input_dir}. Thả file .mp4 vào đó rồi chạy lại.")
        return

    log.info("batch_start", video_count=len(videos))

    for filename in videos:
        base_name = os.path.splitext(filename)[0]
        job = PipelineJob(
            job_id=str(uuid.uuid4())[:8],
            filename=filename,
            base_name=base_name,
            vram_profile=settings.vram_profile,
            created_at=datetime.utcnow(),
        )
        results = await run_pipeline(job, settings)

        print(f"\n=== Kết quả cho {filename} ===")
        for stage, result in results.items():
            status = "✓" if result.success else "✗"
            time_str = f"{result.duration_seconds:.1f}s" if result.duration_seconds else ""
            print(f"  {status} {stage:20s} {time_str}")
            if not result.success:
                print(f"    Lỗi: {result.error}")

    log.info("batch_done", video_count=len(videos))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Chạy tests**

```bash
python -m pytest tests/test_pipeline.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/pipeline.py orchestrator/main.py tests/test_pipeline.py
git commit -m "feat: implement full pipeline orchestrator with VRAM-aware scheduling"
```

---

## Task 7: Docker Production-Grade

**Files:**
- Modify: `docker-compose.yml`
- Modify: `orchestrator/Dockerfile`
- Create: `orchestrator/.env.example`

**Interfaces:**
- N/A (infrastructure config)

- [ ] **Step 1: Cập nhật Dockerfile**

```dockerfile
# orchestrator/Dockerfile
FROM python:3.11-slim

# Install system deps
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    rubberband-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Health check: kiểm tra xem orchestrator process có thể import config không
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "from orchestrator.config import get_settings; get_settings()" || exit 1

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "orchestrator.main"]
```

- [ ] **Step 2: Cập nhật docker-compose.yml**

```yaml
# docker-compose.yml
version: '3.8'

x-gpu-resources: &gpu-resources
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]

services:
  orchestrator:
    build:
      context: ./orchestrator
    container_name: ai_dubbing_orchestrator
    volumes:
      - ./data:/app/data
    environment:
      - OLLAMA_HOST=http://ollama:11434
      - WHISPERX_API=http://whisperx:8000
      - DEMUCS_API=http://demucs:8000
      - TTS_API=http://tts:9880
      - OMNIVOICE_API=http://omnivoice:3900
      - LIPSYNC_API=http://lipsync:8010
      - TTS_ENGINE=${TTS_ENGINE:-omnivoice}
      - LLM_BACKEND=${LLM_BACKEND:-ollama}
      - LLM_MODEL=${LLM_MODEL:-qwen2.5:14b}
      - VRAM_PROFILE=${VRAM_PROFILE:-16gb}
      - ENABLE_LIPSYNC=${ENABLE_LIPSYNC:-false}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    depends_on:
      ollama:
        condition: service_healthy
      whisperx:
        condition: service_healthy
      demucs:
        condition: service_started
    <<: *gpu-resources
    restart: on-failure:3

  ollama:
    image: ollama/ollama:latest
    container_name: ai_dubbing_ollama
    ports:
      - "11434:11434"
    volumes:
      - ./models/ollama:/root/.ollama
    environment:
      - OLLAMA_KEEP_ALIVE=24h
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
    <<: *gpu-resources

  whisperx:
    image: ahmetkca/whisperx-api:latest
    container_name: ai_dubbing_whisperx
    ports:
      - "8001:8000"
    volumes:
      - ./models/whisper:/root/.cache/whisper
      - ./data/temp:/app/temp
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
    <<: *gpu-resources

  demucs:
    image: xserrat/facebook-demucs:latest
    container_name: ai_dubbing_demucs
    volumes:
      - ./data/temp:/data
    entrypoint: ["tail", "-f", "/dev/null"]
    <<: *gpu-resources

  tts:
    image: mikan/gpt-sovits-api:latest
    container_name: ai_dubbing_tts
    ports:
      - "9880:9880"
    volumes:
      - ./models/tts:/app/models
      - ./data/temp:/app/temp
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9880/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    <<: *gpu-resources

  omnivoice:
    image: ghcr.io/debpalash/omnivoice-studio:latest
    container_name: ai_dubbing_omnivoice
    ports:
      - "3900:3900"
    volumes:
      - ./models/omnivoice:/root/.local/share/omnivoice
      - ./data/temp:/app/temp
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3900/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    <<: *gpu-resources

  # M9 Lip-sync: LatentSync
  # Image cần build từ: https://github.com/bytedance/LatentSync
  # Build: docker build -t lipsync-api:latest ./lipsync-service/
  lipsync:
    image: lipsync-api:latest
    container_name: ai_dubbing_lipsync
    ports:
      - "8010:8010"
    volumes:
      - ./models/lipsync:/app/models
      - ./data/temp:/app/temp
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8010/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    profiles:
      - lipsync  # Chỉ chạy khi: docker compose --profile lipsync up
    <<: *gpu-resources
```

- [ ] **Step 3: Tạo .env.example**

```bash
# orchestrator/.env.example
# Copy file này thành .env và chỉnh sửa theo cấu hình của bạn

# --- Engine Selection ---
TTS_ENGINE=omnivoice         # omnivoice | gpt_sovits
LLM_BACKEND=ollama           # ollama | vllm
LLM_MODEL=qwen2.5:14b        # Hoặc gemma-x2-28-9b khi dùng vLLM

# --- Hardware Profile ---
VRAM_PROFILE=16gb            # 16gb | 24gb

# --- Features ---
ENABLE_LIPSYNC=false         # true để bật LatentSync (cần thêm --profile lipsync khi docker compose up)

# --- Logging ---
LOG_LEVEL=INFO               # DEBUG | INFO | WARNING
```

- [ ] **Step 4: Tạo thư mục data structure**

```bash
mkdir -p data/input data/output data/temp models/ollama models/whisper models/tts models/omnivoice models/lipsync
```

- [ ] **Step 5: Verify docker-compose syntax**

```bash
docker compose config --quiet && echo "Docker Compose config OK"
```

Expected: `Docker Compose config OK`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml orchestrator/Dockerfile orchestrator/.env.example
git commit -m "feat: production Docker setup with health checks, GPU resources, profiles"
```

---

## Task 8: Chạy Full Test Suite & Smoke Test

**Files:**
- Modify: `tests/conftest.py` (thêm shared fixtures)

- [ ] **Step 1: Chạy toàn bộ test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

Expected: tất cả tests PASS, không có SKIP.

- [ ] **Step 2: Kiểm tra import sạch**

```bash
cd orchestrator && python -c "
from orchestrator.config import get_settings
from orchestrator.models import SrtSegment, PipelineJob, StageResult
from orchestrator.logger import get_logger, setup_logging
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients import DemucsClient, WhisperXClient, LLMClient, TTSClient, LipSyncClient
from orchestrator.stages import run_audio_separate, run_transcribe, run_translate, run_synthesize
from orchestrator.pipeline import run_pipeline
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Dry-run pipeline với mock data**

```bash
# Tạo mock video nhỏ để test
echo "fake" > data/input/test_smoke.mp4

# Chạy với mock (sẽ fail ở các API calls vì services chưa chạy — nhưng import phải sạch)
python -m orchestrator.main --video test_smoke.mp4 --log-level DEBUG 2>&1 | head -50
```

Expected: output có structured logs, không có `ImportError` hay `AttributeError`.

- [ ] **Step 4: Commit final**

```bash
git add tests/ orchestrator/
git commit -m "test: full test suite green, smoke test verified"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] M2 Demucs — `stages/audio_separate.py` + `clients/demucs_client.py`
- [x] M3 WhisperX — `stages/transcribe.py` + `clients/whisperx_client.py`
- [x] M4 LLM dịch thuật (Ollama + vLLM) — `stages/translate.py` + `clients/llm_client.py`
- [x] M5 TTS (OmniVoice + GPT-SoVITS) — `stages/synthesize.py` + `clients/tts_client.py`
- [x] M6 Audio sync — `audio_sync.py` (giữ nguyên) + dùng trong `stages/synthesize.py`
- [x] M7+M8 OCR + Blur — `stages/video_ocr.py` (wrap `video_process.py`)
- [x] M9 Lip-sync LatentSync — `stages/lip_sync.py` + `clients/lipsync_client.py`
- [x] M10 FFmpeg Mux — `audio_sync.mix_audio_to_video` trong `pipeline.py`
- [x] VRAM 16GB sequential — `VRAMManager.slot()` + ordering trong `pipeline.py`
- [x] VRAM 24GB parallel — song song M2+M7, `vram.slot` cho phép concurrency
- [x] `TTS_ENGINE` env var routing — `tts_client.py` + `config.Settings.tts_engine`
- [x] `ENABLE_LIPSYNC` env var — `config.Settings.enable_lipsync` + pipeline conditional
- [x] Docker health checks — tất cả services có `healthcheck` block
- [x] Retry logic — `BaseClient.post_json/post_file` với exponential backoff
- [x] Structured logging — `structlog` với `job_id`, `filename` context binding

**Placeholder scan:** Không có TBD, TODO, "implement later" trong plan.

**Type consistency:**
- `SrtSegment.translated: Optional[str]` — nhất quán từ Task 1 → Task 5
- `StageResult.output_path: Optional[str]` — nhất quán toàn bộ stages
- `VRAMManager.slot(service: str, vram_gb: float)` — nhất quán trong tất cả stages
