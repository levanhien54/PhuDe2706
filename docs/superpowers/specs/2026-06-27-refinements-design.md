# Refinements Design: Retry, Quality Gate, OCR Optimization

> **Ngày:** 27/06/2026  
> **Scope:** 3 cải tiến độc lập, không thay đổi kiến trúc pipeline

---

## 1. HTTP Retry Refinement

### Vấn đề hiện tại
`base.py` retry mọi lỗi HTTP với cùng chiến lược — kể cả 4xx (lỗi client không bao giờ tự khỏi khi retry), và thời gian chờ cố định `2^attempt` có thể gây thundering herd khi nhiều request cùng fail lúc service restart.

### Thiết kế

**File:** `orchestrator/clients/base.py`

**Luật phân loại:**
- `4xx (400–499)`: **không retry** — raise `ServiceUnavailableError` ngay với message rõ lý do
- `5xx (500–599)`, `ConnectError`, `TimeoutException`: **retry** tối đa `settings.http_retries` lần
- `HTTPStatusError` 4xx: log `http_client_error` với status code, raise ngay
- Jitter: `wait = 2**attempt + random.uniform(0.0, 1.0)` thay vì `wait = 2**attempt`

**Interface không đổi** — chỉ thay đổi logic bên trong `post_json` và `post_file`.

**Ảnh hưởng:** Khi Ollama trả về `404` (model chưa pull) hoặc WhisperX trả về `422` (file không hợp lệ), hệ thống sẽ fail ngay thay vì chờ retry 3 lần.

### Test
- `test_no_retry_on_4xx`: mock 404 → assert ServiceUnavailableError sau 1 lần, không retry
- `test_retry_on_5xx`: mock 3x 500 → assert retry 3 lần
- `test_jitter_applied`: mock thành công lần 2 → assert wait > 2^0 (có jitter)

---

## 2. Automated Quality Gate

### Mục tiêu
Kiểm tra chất lượng kỹ thuật của output video/audio sau pipeline — không cần ground truth, không cần services đang chạy.

### Thiết kế

**File mới:** `orchestrator/quality.py`

4 hàm kiểm tra độc lập, trả về `tuple[bool, str]` (passed, reason):

```
check_file_valid(path: str)
    → (False, "file not found") nếu không tồn tại hoặc size == 0

check_audio_not_silent(path: str, threshold_rms: float = 0.001)
    → (False, "audio silent: rms=0.0003") nếu RMS < threshold
    → Dùng soundfile + numpy

check_stretch_ratio(original_path: str, new_path: str, max_ratio: float)
    → (False, "stretch ratio 2.3 > max 1.5") nếu vượt ngưỡng
    → Dùng librosa.get_duration

check_video_readable(path: str)
    → (False, "cv2 cannot open video") nếu OpenCV không đọc được
```

**File mới:** `tests/integration/test_vi_quality_gate.py`

- Decorator `@pytest.mark.integration` — bỏ qua khi chạy `pytest` thường
- Kích hoạt với: `pytest --integration tests/integration/`
- Fixtures tạo synthetic files:
  - `synthetic_audio(tmp_path)`: sine wave 5 giây, 22050 Hz, soundfile
  - `synthetic_video(tmp_path)`: 150 frames 360p, màu đen, cv2
  - `silent_audio(tmp_path)`: all-zeros WAV
  - `corrupt_file(tmp_path)`: file rỗng `.mp4`
- Test mỗi hàm với input hợp lệ và không hợp lệ

**Script:** `scripts/run_quality_gate.sh`

Chạy pipeline thực trên `data/test_videos/*.mp4`, gọi `quality.py` checks trên output, in bảng:
```
Video            | file_valid | not_silent | stretch_ok | video_ok | PASS/FAIL
my_video.mp4     | ✓          | ✓          | ✗ (1.8x)   | ✓        | FAIL
```

**Config mới trong `config.py`:**
- `quality_silence_threshold: float = Field(0.001, validation_alias="QUALITY_SILENCE_THRESHOLD")`
- `quality_max_video_size_mb: int = Field(1000, validation_alias="QUALITY_MAX_VIDEO_MB")`

---

## 3. OCR Optimization

### Vấn đề hiện tại
`PaddleOCR` chạy cả detection lẫn recognition (đọc nội dung chữ) dù pipeline chỉ cần bounding box để blur. Recognition chiếm ~80% thời gian.

### Thiết kế

**File:** `orchestrator/video_process.py`

**Thay đổi khởi tạo:**
```python
# Trước:
PaddleOCR(use_angle_cls=False, lang='en', use_gpu=True)

# Sau:
PaddleOCR(det=True, rec=False, use_angle_cls=False, use_gpu=True)
```

**Thay đổi parse result** — khi `rec=False`, format trả về khác:
```python
# Trước (rec=True):  line = [box, (text, confidence)]
# Sau  (rec=False):  line = [box, confidence_score]

# Parse mới:
for line in result[0]:
    box, score = line[0], line[1]
    if score < ocr_confidence_threshold:
        continue
    # extract bounding rect từ box...
```

**Config mới trong `config.py`:**
- `ocr_confidence_threshold: float = Field(0.7, validation_alias="OCR_CONFIDENCE_THRESHOLD")`
- `ocr_det_only: bool = Field(True, validation_alias="OCR_DET_ONLY")` — cho phép tắt nếu cần đọc nội dung

**File:** `orchestrator/stages/video_ocr.py` — truyền `settings.ocr_confidence_threshold` xuống `remove_watermark_from_video`.

**Ảnh hưởng dự kiến:** ~4–5x giảm thời gian xử lý OCR mỗi video.

### Test
- `test_ocr_det_only_parse`: verify parse đúng format `[box, score]`
- `test_ocr_filters_low_confidence`: boxes với score < threshold bị bỏ qua

---

## File Structure

```
orchestrator/
├── clients/base.py          — MODIFY: retry classification + jitter
├── config.py                — MODIFY: thêm 4 config fields mới
├── video_process.py         — MODIFY: det=True rec=False, confidence filter
├── quality.py               — CREATE: 4 quality check functions
└── stages/video_ocr.py      — MODIFY: truyền threshold từ settings

tests/
├── test_clients/test_base.py        — MODIFY: thêm 3 tests retry
├── integration/
│   ├── __init__.py                  — CREATE
│   └── test_vi_quality_gate.py      — CREATE: quality check tests
└── test_video_process.py            — CREATE: OCR parse tests

scripts/
└── run_quality_gate.sh              — CREATE: manual integration runner
```

---

## Global Constraints
- Python 3.11+, Pydantic v2
- Không thay đổi interface công khai của bất kỳ module nào
- Test mới dùng `@pytest.mark.integration` cho integration tests
- `ocr_confidence_threshold` range: 0.0–1.0; ngoài range → ValueError
- Tất cả config mới có giá trị default hợp lý — không phá vỡ deployment hiện tại
