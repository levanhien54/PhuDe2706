# Refinements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cải thiện độ tin cậy HTTP (retry thông minh + jitter), bổ sung automated quality gate cho audio/video output, và tăng tốc OCR 4–5x bằng det-only mode.

**Architecture:** 3 tasks hoàn toàn độc lập — Retry sửa `base.py`, Quality Gate tạo `quality.py` mới + integration tests, OCR tối ưu `video_process.py`. Mỗi task tự test và commit riêng.

**Tech Stack:** Python 3.11, httpx, respx (mock HTTP), soundfile, numpy, librosa, cv2, pydantic-settings v2, pytest + pytest.mark.integration.

## Global Constraints

- Python 3.11+, Pydantic v2 (pydantic-settings==2.3.4)
- Không thay đổi interface công khai của bất kỳ module nào
- Test integration dùng `@pytest.mark.integration`, bỏ qua khi `pytest` thường
- `ocr_confidence_threshold` nhận giá trị float 0.0–1.0 (Pydantic validator)
- Tất cả config mới có default hợp lý — không phá vỡ deployment hiện tại
- `PYTHONPATH=C:\Users\sonson\Desktop\PhuDe27.06` khi chạy pytest trên Windows
- Git user đã config: email=zorovhsclone3@gmail.com, name=sonson

---

## File Structure

```
orchestrator/
├── clients/base.py        MODIFY — retry phân loại 4xx vs 5xx, thêm jitter
├── config.py              MODIFY — thêm 4 fields: ocr_confidence_threshold,
│                                   ocr_det_only, quality_silence_threshold,
│                                   quality_max_video_size_mb
├── video_process.py       MODIFY — PaddleOCR det=True rec=False, confidence filter
├── quality.py             CREATE — 4 hàm check trả về tuple[bool, str]
└── stages/video_ocr.py    MODIFY — truyền ocr_confidence_threshold từ settings

tests/
├── test_clients/test_base.py      MODIFY — thêm 3 tests: no_retry_4xx, retry_5xx, jitter
├── test_video_process.py          CREATE — test OCR parse det-only format
├── integration/__init__.py        CREATE — empty
└── integration/test_vi_quality_gate.py  CREATE — quality check tests

scripts/
└── run_quality_gate.sh            CREATE — manual runner in bảng kết quả
```

---

## Task A: HTTP Retry Classification + Jitter

**Files:**
- Modify: `orchestrator/clients/base.py`
- Modify: `tests/test_clients/test_base.py`

**Interfaces:**
- Consumes: `Settings.http_retries`, `Settings.http_timeout`
- Produces: `BaseClient.post_json` / `post_file` — interface không đổi, hành vi thay đổi:
  - 4xx → raise `ServiceUnavailableError` ngay sau 1 lần (không retry)
  - 5xx / network → retry với jitter

- [ ] **Step 1: Thêm 3 tests mới vào test_base.py (failing)**

Mở `tests/test_clients/test_base.py` và append:

```python
@pytest.mark.asyncio
async def test_no_retry_on_4xx(settings):
    """404 không được retry — fail ngay sau 1 lần gọi."""
    with respx.mock:
        route = respx.post("http://test-service/api").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        client = BaseClient("http://test-service", settings)
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await client.post_json("/api", {})
        assert route.call_count == 1  # không retry
        assert "404" in str(exc_info.value)

@pytest.mark.asyncio
async def test_retry_on_5xx_exhausts(settings):
    """500 phải retry đúng settings.http_retries lần rồi mới raise."""
    with respx.mock:
        route = respx.post("http://test-service/api").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )
        client = BaseClient("http://test-service", settings)  # http_retries=2
        with pytest.raises(ServiceUnavailableError):
            await client.post_json("/api", {})
        assert route.call_count == 2  # retry đúng 2 lần (settings fixture)

@pytest.mark.asyncio
async def test_jitter_wait_nonzero(settings, monkeypatch):
    """Wait phải lớn hơn 2^0=1 (có jitter) khi retry lần 1."""
    waits = []
    original_sleep = asyncio.sleep

    async def capture_sleep(delay):
        waits.append(delay)
        # Không sleep thật để test nhanh
    monkeypatch.setattr(asyncio, "sleep", capture_sleep)

    with respx.mock:
        respx.post("http://test-service/api").mock(
            side_effect=[
                httpx.Response(500, json={}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        client = BaseClient("http://test-service", settings)
        await client.post_json("/api", {})

    assert len(waits) == 1
    assert waits[0] >= 1.0   # 2^0=1 + jitter >= 1.0 (jitter >= 0)
    assert waits[0] < 3.0    # không vượt quá 2^0 + 2.0 max jitter
```

Cũng cần thêm import `asyncio` ở đầu file test nếu chưa có:
```python
import asyncio
import pytest
import respx
import httpx
from orchestrator.clients.base import BaseClient, ServiceUnavailableError
from orchestrator.config import Settings
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/test_clients/test_base.py::test_no_retry_on_4xx -v
```

Expected: `FAILED` — `AssertionError: assert 2 == 1` (hiện tại vẫn retry 4xx)

- [ ] **Step 3: Sửa base.py — thêm phân loại lỗi và jitter**

Thay toàn bộ nội dung `orchestrator/clients/base.py`:

```python
import asyncio
import random
import httpx
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class ServiceUnavailableError(Exception):
    pass


def _is_retryable(exc: Exception) -> bool:
    """Chỉ retry server errors (5xx) và network errors. Không retry client errors (4xx)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException))


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
                    if resp.status_code >= 400:
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}", request=resp.request, response=resp
                        )
                    return resp.json()
            except Exception as e:
                if not _is_retryable(e):
                    status = getattr(getattr(e, "response", None), "status_code", "?")
                    log.error("http_client_error", url=url, status=status, error=str(e))
                    raise ServiceUnavailableError(f"Client error {status}: {e}") from e
                last_exc = e
                wait = 2 ** attempt + random.uniform(0.0, 1.0)
                log.warning("http_retry", attempt=attempt + 1, url=url,
                            error=str(e), wait=round(wait, 2))
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(
            f"Failed after {self.settings.http_retries} retries: {last_exc}"
        )

    async def post_file(self, endpoint: str, file_path: str, extra_data: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                    with open(file_path, "rb") as f:
                        import os
                        filename = os.path.basename(file_path)
                        files = {"file": (filename, f, "audio/wav")}
                        data = extra_data or {}
                        resp = await client.post(url, files=files, data=data)
                        if resp.status_code >= 400:
                            raise httpx.HTTPStatusError(
                                f"HTTP {resp.status_code}", request=resp.request, response=resp
                            )
                        return resp.json()
            except Exception as e:
                if not _is_retryable(e):
                    status = getattr(getattr(e, "response", None), "status_code", "?")
                    log.error("http_client_error", url=url, status=status, error=str(e))
                    raise ServiceUnavailableError(f"Client error {status}: {e}") from e
                last_exc = e
                wait = 2 ** attempt + random.uniform(0.0, 1.0)
                log.warning("http_retry", attempt=attempt + 1, url=url,
                            error=str(e), wait=round(wait, 2))
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(
            f"Failed after {self.settings.http_retries} retries: {last_exc}"
        )
```

**Ghi chú:** `os.path.basename` thay cho `file_path.split("/")[-1]` — fix Windows path bug từ review Task 2.

- [ ] **Step 4: Chạy toàn bộ test_base.py**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/test_clients/test_base.py -v
```

Expected: `6 passed` (3 cũ + 3 mới)

- [ ] **Step 5: Commit**

```powershell
git -C "C:\Users\sonson\Desktop\PhuDe27.06" add orchestrator/clients/base.py tests/test_clients/test_base.py
git -C "C:\Users\sonson\Desktop\PhuDe27.06" commit -m "fix: retry classification (no retry 4xx), add jitter to backoff"
```

---

## Task B: Quality Gate Module

**Files:**
- Create: `orchestrator/quality.py`
- Modify: `orchestrator/config.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_vi_quality_gate.py`
- Create: `scripts/run_quality_gate.sh`

**Interfaces:**
- Consumes: `soundfile`, `numpy`, `librosa`, `cv2` (đều đã có trong requirements)
- Produces:
  - `quality.check_file_valid(path: str) -> tuple[bool, str]`
  - `quality.check_audio_not_silent(path: str, threshold_rms: float) -> tuple[bool, str]`
  - `quality.check_stretch_ratio(orig: str, new: str, max_ratio: float) -> tuple[bool, str]`
  - `quality.check_video_readable(path: str) -> tuple[bool, str]`
  - `Settings.quality_silence_threshold: float`
  - `Settings.quality_max_video_size_mb: int`

- [ ] **Step 1: Thêm config fields vào config.py**

Mở `orchestrator/config.py`, thêm vào cuối block `# Tuning`:

```python
    # Quality gate
    quality_silence_threshold: float = Field(0.001, validation_alias="QUALITY_SILENCE_THRESHOLD")
    quality_max_video_size_mb: int = Field(1000, validation_alias="QUALITY_MAX_VIDEO_MB")
    # OCR optimization (Task C sẽ dùng)
    ocr_confidence_threshold: float = Field(0.7, validation_alias="OCR_CONFIDENCE_THRESHOLD")
    ocr_det_only: bool = Field(True, validation_alias="OCR_DET_ONLY")
```

Cũng thêm validator cho `ocr_confidence_threshold`. Thêm import ở đầu file:
```python
from pydantic import Field, field_validator
```

Thêm validator vào class `Settings`:
```python
    @field_validator("ocr_confidence_threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"ocr_confidence_threshold must be 0.0–1.0, got {v}")
        return v
```

- [ ] **Step 2: Chạy test config để xác nhận vẫn pass**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/test_config.py -v
```

Expected: `3 passed`

- [ ] **Step 3: Viết integration tests (failing)**

Tạo `tests/integration/__init__.py` (empty).

Tạo `tests/integration/test_vi_quality_gate.py`:

```python
import os
import math
import numpy as np
import soundfile as sf
import cv2
import pytest
from orchestrator.quality import (
    check_file_valid,
    check_audio_not_silent,
    check_stretch_ratio,
    check_video_readable,
)

# Đăng ký marker để pytest không warn
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test")


# ---------------------------------------------------------------------------
# Fixtures: tạo synthetic files trong tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_audio(tmp_path):
    """Sine wave 5 giây, 22050 Hz — audio hợp lệ, không silent."""
    path = str(tmp_path / "valid_audio.wav")
    sr = 22050
    t = np.linspace(0, 5.0, sr * 5)
    audio = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    sf.write(path, audio, sr)
    return path


@pytest.fixture
def synthetic_audio_long(tmp_path):
    """Sine wave 10 giây — dùng để test stretch ratio."""
    path = str(tmp_path / "long_audio.wav")
    sr = 22050
    t = np.linspace(0, 10.0, sr * 10)
    audio = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    sf.write(path, audio, sr)
    return path


@pytest.fixture
def synthetic_audio_short(tmp_path):
    """Sine wave 4 giây — stretch ratio = 10/4 = 2.5x (vượt max 1.5)."""
    path = str(tmp_path / "short_audio.wav")
    sr = 22050
    t = np.linspace(0, 4.0, sr * 4)
    audio = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    sf.write(path, audio, sr)
    return path


@pytest.fixture
def silent_audio(tmp_path):
    """All-zeros WAV — audio silent."""
    path = str(tmp_path / "silent.wav")
    sf.write(path, np.zeros(22050 * 3, dtype=np.float32), 22050)
    return path


@pytest.fixture
def synthetic_video(tmp_path):
    """150 frames 360x240 màu đen — video hợp lệ."""
    path = str(tmp_path / "valid_video.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, 30.0, (360, 240))
    for _ in range(150):
        out.write(np.zeros((240, 360, 3), dtype=np.uint8))
    out.release()
    return path


@pytest.fixture
def corrupt_file(tmp_path):
    """File rỗng giả làm .mp4."""
    path = str(tmp_path / "corrupt.mp4")
    open(path, "w").close()  # tạo file rỗng
    return path


# ---------------------------------------------------------------------------
# Tests: check_file_valid
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_file_valid_ok(synthetic_audio):
    passed, reason = check_file_valid(synthetic_audio)
    assert passed is True
    assert reason == "ok"


@pytest.mark.integration
def test_file_valid_not_found(tmp_path):
    passed, reason = check_file_valid(str(tmp_path / "nonexistent.wav"))
    assert passed is False
    assert "not found" in reason


@pytest.mark.integration
def test_file_valid_empty(corrupt_file):
    passed, reason = check_file_valid(corrupt_file)
    assert passed is False
    assert "empty" in reason


# ---------------------------------------------------------------------------
# Tests: check_audio_not_silent
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_audio_not_silent_ok(synthetic_audio):
    passed, reason = check_audio_not_silent(synthetic_audio, threshold_rms=0.001)
    assert passed is True


@pytest.mark.integration
def test_audio_silent_fails(silent_audio):
    passed, reason = check_audio_not_silent(silent_audio, threshold_rms=0.001)
    assert passed is False
    assert "silent" in reason
    assert "rms=" in reason


# ---------------------------------------------------------------------------
# Tests: check_stretch_ratio
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_stretch_ratio_ok(synthetic_audio_long, synthetic_audio):
    """10s gốc → 5s mới = ratio 2.0x. max_ratio=2.5 → pass."""
    passed, reason = check_stretch_ratio(synthetic_audio_long, synthetic_audio, max_ratio=2.5)
    assert passed is True


@pytest.mark.integration
def test_stretch_ratio_exceeds(synthetic_audio_long, synthetic_audio_short):
    """10s gốc → 4s mới = ratio 2.5x. max_ratio=1.5 → fail."""
    passed, reason = check_stretch_ratio(synthetic_audio_long, synthetic_audio_short, max_ratio=1.5)
    assert passed is False
    assert "stretch ratio" in reason
    assert "1.5" in reason


# ---------------------------------------------------------------------------
# Tests: check_video_readable
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_video_readable_ok(synthetic_video):
    passed, reason = check_video_readable(synthetic_video)
    assert passed is True


@pytest.mark.integration
def test_video_readable_corrupt(corrupt_file):
    passed, reason = check_video_readable(corrupt_file)
    assert passed is False
    assert "cannot open" in reason
```

- [ ] **Step 4: Chạy để xác nhận tests bị skip (chưa có quality.py)**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/integration/ -v -m integration
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'orchestrator.quality'`

- [ ] **Step 5: Implement quality.py**

Tạo `orchestrator/quality.py`:

```python
import os
import numpy as np
import soundfile as sf
import librosa
import cv2
from orchestrator.logger import get_logger

log = get_logger(__name__)


def check_file_valid(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"file not found: {path}"
    if os.path.getsize(path) == 0:
        return False, f"file empty: {path}"
    return True, "ok"


def check_audio_not_silent(path: str, threshold_rms: float = 0.001) -> tuple[bool, str]:
    try:
        data, _ = sf.read(path)
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
        if rms < threshold_rms:
            return False, f"audio silent: rms={rms:.6f} < threshold={threshold_rms}"
        return True, f"rms={rms:.4f}"
    except Exception as e:
        return False, f"audio read error: {e}"


def check_stretch_ratio(original_path: str, new_path: str, max_ratio: float) -> tuple[bool, str]:
    try:
        orig_dur = librosa.get_duration(path=original_path)
        new_dur = librosa.get_duration(path=new_path)
        if new_dur <= 0:
            return False, "new audio has zero duration"
        ratio = orig_dur / new_dur
        if ratio > max_ratio:
            return False, f"stretch ratio {ratio:.2f}x > max {max_ratio}x"
        return True, f"ratio={ratio:.2f}x"
    except Exception as e:
        return False, f"duration check error: {e}"


def check_video_readable(path: str) -> tuple[bool, str]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        return False, f"cv2 cannot open video: {path}"
    ret, _ = cap.read()
    cap.release()
    if not ret:
        return False, f"video has no readable frames: {path}"
    return True, "ok"
```

- [ ] **Step 6: Chạy integration tests**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/integration/ -v -m integration
```

Expected: `11 passed`

- [ ] **Step 7: Tạo scripts/run_quality_gate.sh**

Tạo thư mục `scripts/` nếu chưa có. Tạo `scripts/run_quality_gate.sh`:

```bash
#!/usr/bin/env bash
# Chạy quality gate trên tất cả video trong data/test_videos/
# Sử dụng: bash scripts/run_quality_gate.sh
# Yêu cầu: pip install -r orchestrator/requirements.txt

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
export PYTHONPATH="$PROJECT_ROOT"

INPUT_DIR="$PROJECT_ROOT/data/test_videos"
OUTPUT_DIR="$PROJECT_ROOT/data/output"

if [[ ! -d "$INPUT_DIR" ]] || [[ -z "$(ls "$INPUT_DIR"/*.mp4 2>/dev/null)" ]]; then
    echo "Không tìm thấy video trong $INPUT_DIR"
    echo "Bỏ video .mp4 thử nghiệm vào data/test_videos/ rồi chạy lại."
    exit 1
fi

python3 - << 'PYEOF'
import os, sys
PROJECT_ROOT = os.environ.get("PYTHONPATH", ".")
sys.path.insert(0, PROJECT_ROOT)

from orchestrator.quality import (
    check_file_valid, check_audio_not_silent,
    check_stretch_ratio, check_video_readable,
)
from orchestrator.config import get_settings

settings = get_settings()
input_dir  = os.path.join(settings.data_dir, "test_videos")
output_dir = os.path.join(settings.data_dir, "output")

videos = [f for f in os.listdir(input_dir) if f.endswith(".mp4")]
if not videos:
    print(f"Không có video trong {input_dir}")
    sys.exit(1)

header = f"{'Video':<30} | {'file':<6} | {'audio':<7} | {'stretch':<10} | {'video':<7} | RESULT"
print(header)
print("-" * len(header))

all_pass = True
for v in sorted(videos):
    base   = os.path.splitext(v)[0]
    out_mp4 = os.path.join(output_dir, f"{base}_dubbed.mp4")
    out_wav = os.path.join(output_dir, f"{base}_new_vocal.wav")
    in_wav  = os.path.join(input_dir.replace("test_videos", "temp"), base, "vocal.wav")

    f_ok, _  = check_file_valid(out_mp4)
    a_ok, am = check_audio_not_silent(out_wav if os.path.exists(out_wav) else out_mp4,
                                      settings.quality_silence_threshold)
    s_ok, sm = check_stretch_ratio(
        in_wav if os.path.exists(in_wav) else out_mp4,
        out_wav if os.path.exists(out_wav) else out_mp4,
        settings.tts_max_ratio,
    ) if os.path.exists(in_wav) else (True, "skip")
    v_ok, _  = check_video_readable(out_mp4) if f_ok else (False, "skip")

    result = "PASS" if all([f_ok, a_ok, s_ok, v_ok]) else "FAIL"
    if result == "FAIL":
        all_pass = False

    def sym(b): return "✓" if b else "✗"
    stretch_str = sm if not s_ok else "✓"
    print(f"{v:<30} | {sym(f_ok):<6} | {sym(a_ok):<7} | {stretch_str:<10} | {sym(v_ok):<7} | {result}")

print()
print("Tổng kết:", "TẤT CẢ PASS ✓" if all_pass else "CÓ LỖI ✗")
sys.exit(0 if all_pass else 1)
PYEOF
```

- [ ] **Step 8: Chạy lại full test suite để xác nhận không regression**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/ -v --ignore=tests/integration
```

Expected: `18 passed` (giống trước)

- [ ] **Step 9: Commit**

```powershell
git -C "C:\Users\sonson\Desktop\PhuDe27.06" add orchestrator/quality.py orchestrator/config.py tests/integration/ scripts/run_quality_gate.sh
git -C "C:\Users\sonson\Desktop\PhuDe27.06" commit -m "feat: add quality gate module + integration tests + quality_gate script"
```

---

## Task C: OCR det-only Optimization

**Files:**
- Modify: `orchestrator/video_process.py`
- Modify: `orchestrator/stages/video_ocr.py`
- Create: `tests/test_video_process.py`

**Interfaces:**
- Consumes: `Settings.ocr_confidence_threshold`, `Settings.ocr_det_only` (đã thêm trong Task B)
- Produces:
  - `remove_watermark_from_video(input_path, output_path, confidence_threshold=0.7, det_only=True)`  
    Signature mở rộng với 2 tham số mới có default — backward compatible

- [ ] **Step 1: Viết tests (failing)**

Tạo `tests/test_video_process.py`:

```python
import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Test parse kết quả det-only (rec=False) của PaddleOCR
# Format: [[box_points, confidence_score], ...]
# ---------------------------------------------------------------------------

def make_det_only_result(boxes_with_scores):
    """Tạo mock result giống PaddleOCR khi rec=False."""
    result = []
    for box, score in boxes_with_scores:
        result.append([box, score])
    return [result]  # PaddleOCR luôn wrap trong list ngoài


def parse_det_only_boxes(result, confidence_threshold, frame_width, frame_height):
    """Hàm parse tương tự logic mới trong video_process.py."""
    from orchestrator.video_process import _parse_det_only_boxes
    return _parse_det_only_boxes(result, confidence_threshold, frame_width, frame_height)


def test_det_only_parse_returns_boxes():
    """Parse đúng format [box, score] khi score >= threshold."""
    box = [[10, 20], [100, 20], [100, 40], [10, 40]]
    result = make_det_only_result([(box, 0.9)])
    boxes = parse_det_only_boxes(result, confidence_threshold=0.7,
                                  frame_width=640, frame_height=480)
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert x == 5    # 10 - pad(5) = 5
    assert y == 15   # 20 - pad(5) = 15
    assert w > 0
    assert h > 0


def test_det_only_filters_low_confidence():
    """Box với score < threshold bị bỏ qua."""
    box = [[10, 20], [100, 20], [100, 40], [10, 40]]
    result = make_det_only_result([(box, 0.3)])
    boxes = parse_det_only_boxes(result, confidence_threshold=0.7,
                                  frame_width=640, frame_height=480)
    assert boxes == []


def test_det_only_clamps_to_frame():
    """Box vượt ra ngoài frame bị clamp về 0."""
    box = [[-10, -5], [700, -5], [700, 50], [-10, 50]]
    result = make_det_only_result([(box, 0.95)])
    boxes = parse_det_only_boxes(result, confidence_threshold=0.7,
                                  frame_width=640, frame_height=480)
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert x == 0
    assert y == 0
    assert x + w <= 640
    assert y + h <= 480


def test_det_only_empty_result():
    """Kết quả OCR rỗng trả về list rỗng."""
    boxes = parse_det_only_boxes([None], confidence_threshold=0.7,
                                  frame_width=640, frame_height=480)
    assert boxes == []
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/test_video_process.py -v
```

Expected: `ImportError: cannot import name '_parse_det_only_boxes'`

- [ ] **Step 3: Cập nhật video_process.py**

Thay toàn bộ nội dung `orchestrator/video_process.py`:

```python
import os
import cv2
import math
import numpy as np
from paddleocr import PaddleOCR

_ocr_instance = None
_ocr_det_only: bool = True


def get_ocr_instance(det_only: bool = True):
    global _ocr_instance, _ocr_det_only
    if _ocr_instance is None or _ocr_det_only != det_only:
        _ocr_det_only = det_only
        _ocr_instance = PaddleOCR(
            det=True,
            rec=not det_only,       # rec=False khi det_only=True → ~5x nhanh hơn
            use_angle_cls=False,
            use_gpu=True,
        )
    return _ocr_instance


def _parse_det_only_boxes(
    result, confidence_threshold: float, frame_width: int, frame_height: int
) -> list[tuple[int, int, int, int]]:
    """
    Parse kết quả PaddleOCR khi rec=False.
    Format mỗi item: [box_points, confidence_score]
    box_points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    Trả về list (x, y, w, h) đã pad 5px và clamp theo frame size.
    """
    boxes = []
    if not result or not result[0]:
        return boxes
    pad = 5
    for item in result[0]:
        try:
            box, score = item[0], item[1]
            if score < confidence_threshold:
                continue
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]
            x_min = int(min(x_coords))
            y_min = int(min(y_coords))
            x_max = int(max(x_coords))
            y_max = int(max(y_coords))

            x = max(0, x_min - pad)
            y = max(0, y_min - pad)
            w = min(frame_width - x, (x_max - x_min) + pad * 2)
            h = min(frame_height - y, (y_max - y_min) + pad * 2)

            if w > 0 and h > 0:
                boxes.append((x, y, w, h))
        except Exception:
            continue
    return boxes


def _parse_rec_boxes(
    result, frame_width: int, frame_height: int
) -> list[tuple[int, int, int, int]]:
    """
    Parse kết quả PaddleOCR khi rec=True (legacy mode).
    Format mỗi item: [box_points, (text, confidence)]
    """
    boxes = []
    if not result or not result[0]:
        return boxes
    pad = 5
    for line in result[0]:
        try:
            box = line[0]
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]
            x_min, x_max = int(min(x_coords)), int(max(x_coords))
            y_min, y_max = int(min(y_coords)), int(max(y_coords))
            x = max(0, x_min - pad)
            y = max(0, y_min - pad)
            w = min(frame_width - x, (x_max - x_min) + pad * 2)
            h = min(frame_height - y, (y_max - y_min) + pad * 2)
            if w > 0 and h > 0:
                boxes.append((x, y, w, h))
        except Exception:
            continue
    return boxes


def apply_blur_to_frame(frame, boxes):
    """Làm mờ các vùng chứa chữ bằng Gaussian Blur."""
    height, width = frame.shape[:2]
    for (x, y, w, h) in boxes:
        roi = frame[y:y + h, x:x + w]
        if roi.size == 0:
            continue
        kernel_w = max(3, min(w if w % 2 != 0 else w - 1, 51))
        kernel_h = max(3, min(h if h % 2 != 0 else h - 1, 51))
        frame[y:y + h, x:x + w] = cv2.GaussianBlur(roi, (kernel_w, kernel_h), 0)
    return frame


def remove_watermark_from_video(
    input_path: str,
    output_path: str,
    confidence_threshold: float = 0.7,
    det_only: bool = True,
):
    """
    Phát hiện và làm mờ chữ động trong video.
    det_only=True: chỉ dùng detection (~5x nhanh hơn, không đọc nội dung chữ).
    """
    print(f"[VideoProcess] Bắt đầu xử lý: {input_path} (det_only={det_only})")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"[VideoProcess] Lỗi: Không thể mở video {input_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if math.isnan(fps) or fps == 0:
        fps = 25.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    ocr = get_ocr_instance(det_only=det_only)

    frame_skip = max(1, int(fps / 2))
    cached_boxes: list[tuple[int, int, int, int]] = []
    frame_count = 0

    print(f"[VideoProcess] {total} frames, OCR mỗi {frame_skip} frames.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % frame_skip == 0:
            result = ocr.ocr(frame, cls=False)
            if det_only:
                cached_boxes = _parse_det_only_boxes(
                    result, confidence_threshold, width, height
                )
            else:
                cached_boxes = _parse_rec_boxes(result, width, height)

        if cached_boxes:
            frame = apply_blur_to_frame(frame, cached_boxes)

        out.write(frame)
        frame_count += 1
        if frame_count % (int(fps) * 5) == 0:
            print(f"[VideoProcess] {frame_count}/{total} frames...")

    cap.release()
    out.release()
    print(f"[VideoProcess] Hoàn tất: {output_path}")
```

- [ ] **Step 4: Cập nhật stages/video_ocr.py để truyền settings**

Mở `orchestrator/stages/video_ocr.py`, tìm dòng gọi `remove_watermark_from_video`:

```python
# Trước:
await asyncio.to_thread(remove_watermark_from_video, input_video, output_video)

# Sau:
await asyncio.to_thread(
    remove_watermark_from_video,
    input_video,
    output_video,
    confidence_threshold=settings.ocr_confidence_threshold,
    det_only=settings.ocr_det_only,
)
```

- [ ] **Step 5: Chạy tests OCR**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/test_video_process.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Chạy full test suite (không integration)**

```powershell
$env:PYTHONPATH = "C:\Users\sonson\Desktop\PhuDe27.06"
python -m pytest tests/ --ignore=tests/integration -v
```

Expected: `22 passed` (18 cũ + 4 mới)

- [ ] **Step 7: Commit**

```powershell
git -C "C:\Users\sonson\Desktop\PhuDe27.06" add orchestrator/video_process.py orchestrator/stages/video_ocr.py tests/test_video_process.py
git -C "C:\Users\sonson\Desktop\PhuDe27.06" commit -m "perf: OCR det-only mode (~5x faster), confidence threshold filter"
```

---

## Self-Review

**Spec coverage:**
- [x] Retry: không retry 4xx, retry 5xx+network, jitter `2^n + uniform(0,1)` — Task A
- [x] Quality gate: 4 hàm check, tuple[bool, str], integration tests, script — Task B
- [x] OCR det_only, confidence_threshold, backward compatible signature — Task C
- [x] Config: 4 fields mới với defaults, validator threshold 0.0–1.0 — Task B Step 1
- [x] `os.path.basename` fix cho Windows path — Task A Step 3

**Placeholder scan:** Không có TBD hay "implement later".

**Type consistency:**
- `_parse_det_only_boxes` được define trong Task C Step 3 và import trong test Task C Step 1 ✓
- `check_file_valid`, `check_audio_not_silent`, `check_stretch_ratio`, `check_video_readable` — define Task B Step 5, import Task B Step 3 ✓
- `Settings.ocr_confidence_threshold` define Task B Step 1, dùng Task C Step 4 ✓
