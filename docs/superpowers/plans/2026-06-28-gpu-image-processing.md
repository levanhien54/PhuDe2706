# GPU Image Processing Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tăng tốc và chất lượng watermark removal bằng temporal reference inpainting + OCR batch pre-pass, trên 24GB GPU.

**Architecture:** Thêm 2 pre-pass trước pipeline chính: (1) `precompute_ocr_results()` chạy PaddleOCR theo batch trên các OCR frames, (2) `build_temporal_reference()` tính pixel-wise median làm clean background. Pipeline 4-thread giữ nguyên cấu trúc; inpaint thread dùng temporal copy cho static boxes thay vì TELEA.

**Tech Stack:** Python 3.11, OpenCV (cv2), PaddleOCR, NumPy, pytest

## Global Constraints

- Python 3.11, OpenCV >= 4.8, PaddleOCR >= 2.7
- Backward compat: `remove_watermark_from_video(path, out, mask_only)` vẫn hoạt động khi `settings=None`
- Tests dùng synthetic numpy frames — không cần GPU, không cần video file thật (ngoại trừ `build_temporal_reference` và `precompute_ocr_results` test dùng helper `_make_test_video`)
- Không thay đổi VRAMManager, pipeline.py, threading architecture
- Run all tests: `python -m pytest tests/ -v` — phải pass 100%

---

## File Map

| File | Action | Thay đổi |
|---|---|---|
| `orchestrator/config.py` | Modify | Thêm `ocr_batch_size: int = Field(4, ...)` |
| `orchestrator/video_process.py` | Modify | Thêm `build_temporal_reference()`, `apply_temporal_inpaint()`, `precompute_ocr_results()`; fix nvenc cache, `ocr_fps` từ settings, `_detect_static_boxes` 30-frame; integrate vào `remove_watermark_from_video()` |
| `orchestrator/stages/video_ocr.py` | Modify | Pass `settings=settings` vào `remove_watermark_from_video()` |
| `tests/test_video_process.py` | Create | Unit tests cho mọi function mới |
| `tests/test_config.py` | Modify | Thêm test `ocr_batch_size` |

---

## Task 1: Config `ocr_batch_size` + nvenc cache + settings param

**Files:**
- Modify: `orchestrator/config.py`
- Modify: `orchestrator/video_process.py` (phần đầu file + signature `remove_watermark_from_video`)
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.ocr_batch_size: int`, `_check_nvenc_cached() -> bool`, signature `remove_watermark_from_video(input_path, output_path, mask_only=False, settings=None)`

---

- [ ] **Step 1: Thêm `ocr_batch_size` vào `orchestrator/config.py`**

Thêm dòng sau `tts_max_ratio`:
```python
    ocr_batch_size: int = Field(4, validation_alias="OCR_BATCH_SIZE")
```

File sau khi sửa (phần Tuning):
```python
    # Tuning
    http_timeout: float = Field(300.0, validation_alias="HTTP_TIMEOUT")
    http_retries: int = Field(3, validation_alias="HTTP_RETRIES")
    ocr_fps: float = Field(2.0, validation_alias="OCR_FPS")
    tts_max_ratio: float = Field(1.5, validation_alias="TTS_MAX_RATIO")
    ocr_batch_size: int = Field(4, validation_alias="OCR_BATCH_SIZE")
```

- [ ] **Step 2: Viết failing tests cho config**

Thêm vào `tests/test_config.py`:
```python
def test_ocr_batch_size_default():
    s = Settings()
    assert s.ocr_batch_size == 4

def test_ocr_batch_size_override(monkeypatch):
    monkeypatch.setenv("OCR_BATCH_SIZE", "8")
    s = Settings()
    assert s.ocr_batch_size == 8
```

- [ ] **Step 3: Chạy test để verify fail**

```
python -m pytest tests/test_config.py::test_ocr_batch_size_default -v
```
Expected: FAIL — `Settings` chưa có `ocr_batch_size`

- [ ] **Step 4: Chạy lại sau khi đã thêm field vào config.py**

```
python -m pytest tests/test_config.py -v
```
Expected: tất cả PASS

- [ ] **Step 5: Cache nvenc + fix signature trong `orchestrator/video_process.py`**

Thay thế `check_nvenc()` function và `remove_watermark_from_video` signature:

```python
# Thêm ở đầu file (sau imports)
_NVENC_AVAILABLE: bool | None = None

def _check_nvenc_cached() -> bool:
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is None:
        try:
            res = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True
            )
            _NVENC_AVAILABLE = 'h264_nvenc' in res.stdout
        except Exception:
            _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE
```

Xóa hàm `check_nvenc()` cũ (inline bên trong `FFmpegWriter.__init__`).

Sửa signature `remove_watermark_from_video`:
```python
def remove_watermark_from_video(
    input_path: str,
    output_path: str,
    mask_only: bool = False,
    settings=None,
):
```

Thêm ngay đầu hàm sau docstring:
```python
    _ocr_fps = settings.ocr_fps if settings is not None else 2.0
    _ocr_batch_size = settings.ocr_batch_size if settings is not None else 4
```

Đổi `ocr_fps = 2.0` tại line 238 thành biến `_ocr_fps` đã tính ở trên.

Trong `FFmpegWriter.__init__`, thay `check_nvenc()` thành `_check_nvenc_cached()`.

- [ ] **Step 6: Chạy full tests**

```
python -m pytest tests/ -v
```
Expected: tất cả PASS (không regression)

- [ ] **Step 7: Commit**

```bash
git add orchestrator/config.py orchestrator/video_process.py tests/test_config.py
git commit -m "feat(video_process): add ocr_batch_size config, cache nvenc, settings param"
```

---

## Task 2: `build_temporal_reference()`

**Files:**
- Modify: `orchestrator/video_process.py` — thêm function
- Create: `tests/test_video_process.py` — helper + tests

**Interfaces:**
- Produces: `build_temporal_reference(input_path: str, n_samples: int = 20) -> np.ndarray | None`
  - Returns: `ndarray shape (H, W, 3) dtype uint8`, hoặc `None` nếu video < 3 frames hoặc lỗi

---

- [ ] **Step 1: Tạo `tests/test_video_process.py` với helper + failing test**

```python
import os
import tempfile
import numpy as np
import cv2
import pytest
from orchestrator.video_process import (
    build_temporal_reference,
    apply_temporal_inpaint,
    precompute_ocr_results,
)


def _make_test_video(path: str, n_frames: int = 30, h: int = 50, w: int = 50) -> None:
    """Tạo video synthetic dùng MJPG codec (không cần ffmpeg)."""
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    writer = cv2.VideoWriter(path, fourcc, 10.0, (w, h))
    assert writer.isOpened(), f"VideoWriter failed for {path}"
    for i in range(n_frames):
        # Frame màu xám với giá trị tăng dần để median dễ tính
        frame = np.full((h, w, 3), min(i * 8, 200), dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_build_temporal_reference_shape():
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=30, h=50, w=50)
        result = build_temporal_reference(path, n_samples=10)
        assert result is not None
        assert result.shape == (50, 50, 3)
        assert result.dtype == np.uint8
    finally:
        os.unlink(path)


def test_build_temporal_reference_short_video_returns_none():
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=2)
        result = build_temporal_reference(path, n_samples=10)
        assert result is None
    finally:
        os.unlink(path)


def test_build_temporal_reference_invalid_path():
    result = build_temporal_reference("/nonexistent/path.avi", n_samples=5)
    assert result is None
```

- [ ] **Step 2: Chạy test để verify fail**

```
python -m pytest tests/test_video_process.py::test_build_temporal_reference_shape -v
```
Expected: ImportError — `build_temporal_reference` chưa tồn tại

- [ ] **Step 3: Implement `build_temporal_reference` trong `orchestrator/video_process.py`**

Thêm function sau `_detect_static_boxes`:

```python
def build_temporal_reference(input_path: str, n_samples: int = 20) -> np.ndarray | None:
    """Sample n_samples frames đều toàn video, tính median → clean background."""
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 3:
        cap.release()
        return None

    n = min(n_samples, total_frames)
    if n < 2:
        cap.release()
        return None

    indices = [int(i * (total_frames - 1) / (n - 1)) for i in range(n)]

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)

    cap.release()

    if len(frames) < 3:
        return None

    stack = np.stack(frames, axis=0).astype(np.float32)
    return np.median(stack, axis=0).astype(np.uint8)
```

- [ ] **Step 4: Chạy tests**

```
python -m pytest tests/test_video_process.py -v -k "temporal_reference"
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/video_process.py tests/test_video_process.py
git commit -m "feat(video_process): add build_temporal_reference for clean background pre-computation"
```

---

## Task 3: `apply_temporal_inpaint()`

**Files:**
- Modify: `orchestrator/video_process.py`
- Modify: `tests/test_video_process.py`

**Interfaces:**
- Consumes: `build_temporal_reference()` output (ndarray hoặc None)
- Produces: `apply_temporal_inpaint(frame, reference, static_boxes, dynamic_boxes) -> np.ndarray`
  - `static_boxes`: list of `(x, y, w, h)` — fill từ reference
  - `dynamic_boxes`: list of `(x, y, w, h)` — dùng TELEA
  - `reference=None` → static_boxes gộp vào dynamic_boxes, TELEA toàn bộ

---

- [ ] **Step 1: Thêm failing tests vào `tests/test_video_process.py`**

```python
def test_apply_temporal_inpaint_static_copies_from_reference():
    """Static box phải lấy pixel từ reference, không phải frame gốc."""
    frame = np.zeros((60, 60, 3), dtype=np.uint8)
    frame[10:20, 10:30] = 255  # watermark trắng

    reference = np.full((60, 60, 3), 100, dtype=np.uint8)  # background xám

    result = apply_temporal_inpaint(frame, reference, static_boxes=[(10, 10, 20, 10)], dynamic_boxes=[])

    # Vùng watermark phải là màu reference (100), không phải 255
    assert np.all(result[10:20, 10:30] == 100)
    # Vùng ngoài watermark giữ nguyên (0)
    assert np.all(result[0:10, :] == 0)


def test_apply_temporal_inpaint_no_boxes_returns_copy():
    """Không có box → trả về copy của frame gốc."""
    frame = np.full((40, 40, 3), 77, dtype=np.uint8)
    result = apply_temporal_inpaint(frame, None, [], [])
    np.testing.assert_array_equal(result, frame)
    assert result is not frame  # phải là copy


def test_apply_temporal_inpaint_fallback_no_reference():
    """reference=None → không crash, trả về ndarray cùng shape."""
    frame = np.full((60, 60, 3), 50, dtype=np.uint8)
    result = apply_temporal_inpaint(frame, None, static_boxes=[(5, 5, 10, 10)], dynamic_boxes=[])
    assert result.shape == frame.shape
    assert result.dtype == np.uint8
```

- [ ] **Step 2: Chạy tests để verify fail**

```
python -m pytest tests/test_video_process.py -v -k "temporal_inpaint"
```
Expected: ImportError — `apply_temporal_inpaint` chưa tồn tại

- [ ] **Step 3: Implement `apply_temporal_inpaint` trong `orchestrator/video_process.py`**

Thêm sau `build_temporal_reference`:

```python
def apply_temporal_inpaint(
    frame: np.ndarray,
    reference: np.ndarray | None,
    static_boxes: list[tuple],
    dynamic_boxes: list[tuple],
) -> np.ndarray:
    """
    Inpaint static boxes từ temporal reference (pixel copy, rất nhanh).
    Inpaint dynamic boxes bằng TELEA (như cũ).
    Nếu reference=None, gộp static vào dynamic để TELEA xử lý hết.
    """
    result = frame.copy()

    if reference is not None:
        h_f, w_f = frame.shape[:2]
        for (x, y, w, h) in static_boxes:
            y2 = min(y + h, h_f)
            x2 = min(x + w, w_f)
            result[y:y2, x:x2] = reference[y:y2, x:x2]
        all_dynamic = list(dynamic_boxes)
    else:
        # Fallback: xử lý static bằng TELEA
        all_dynamic = list(static_boxes) + list(dynamic_boxes)

    if not all_dynamic:
        return result

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for (x, y, w, h) in all_dynamic:
        pad = 3
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        mask[y1:y2, x1:x2] = 255

    if mask.max() == 0:
        return result

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        cx1 = max(0, x - 10)
        cy1 = max(0, y - 10)
        cx2 = min(frame.shape[1], x + w + 10)
        cy2 = min(frame.shape[0], y + h + 10)
        crop_frame = result[cy1:cy2, cx1:cx2]
        crop_mask = mask[cy1:cy2, cx1:cx2]
        result[cy1:cy2, cx1:cx2] = cv2.inpaint(crop_frame, crop_mask, 3, cv2.INPAINT_TELEA)

    return result
```

- [ ] **Step 4: Chạy tests**

```
python -m pytest tests/test_video_process.py -v -k "temporal_inpaint"
```
Expected: 3 tests PASS

- [ ] **Step 5: Chạy full test suite**

```
python -m pytest tests/ -v
```
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/video_process.py tests/test_video_process.py
git commit -m "feat(video_process): add apply_temporal_inpaint — pixel copy for static watermarks"
```

---

## Task 4: `precompute_ocr_results()` — OCR Batch Pre-Pass

**Files:**
- Modify: `orchestrator/video_process.py`
- Modify: `tests/test_video_process.py`

**Strategy:** Pre-pass riêng biệt đọc video, gom các OCR frames thành batch, trả về `dict[frame_idx → list[box]]`. Pipeline chính lookup dict này thay vì gọi OCR real-time.

**Interfaces:**
- Consumes: `_scale_frame_for_ocr()`, `_parse_ocr_boxes()`, `_ocr_lock`
- Produces: `precompute_ocr_results(input_path, total_frames, fps, ocr_fps, ocr_batch_size, width, height, ocr) -> dict[int, list[tuple]]`
  - key: frame index, value: list of `(x, y, w, h)`

---

- [ ] **Step 1: Thêm failing tests vào `tests/test_video_process.py`**

```python
from unittest.mock import MagicMock, patch, call


def test_precompute_ocr_results_batch_call_count():
    """Với 12 OCR frames và batch_size=4, phải gọi ocr.ocr đúng 3 lần."""
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=120, h=50, w=50)
        cap = cv2.VideoCapture(path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        mock_ocr = MagicMock()
        # ocr.ocr(batch) trả về list of results, mỗi result là []
        mock_ocr.ocr.return_value = [[] for _ in range(4)]

        # 120 frames @ fps=10, ocr_fps=1 → frame_skip=10 → OCR frames: 0,10,20,...,110 = 12 frames
        # batch_size=4 → ceil(12/4) = 3 batch calls
        result = precompute_ocr_results(
            path, total_frames, fps,
            ocr_fps=1.0, ocr_batch_size=4,
            width=width, height=height, ocr=mock_ocr
        )
        assert mock_ocr.ocr.call_count == 3
        assert isinstance(result, dict)
    finally:
        os.unlink(path)


def test_precompute_ocr_results_returns_correct_keys():
    """Keys trong dict phải là frame indices tương ứng với OCR frames."""
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=30, h=50, w=50)
        cap = cv2.VideoCapture(path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        mock_ocr = MagicMock()
        mock_ocr.ocr.return_value = [[]]  # single-item batch

        result = precompute_ocr_results(
            path, total, fps,
            ocr_fps=1.0, ocr_batch_size=1,
            width=w, height=h, ocr=mock_ocr
        )
        # fps=10, ocr_fps=1 → frame_skip=10 → keys: 0, 10, 20
        expected_keys = {0, 10, 20}
        assert set(result.keys()) == expected_keys
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Chạy tests để verify fail**

```
python -m pytest tests/test_video_process.py -v -k "precompute_ocr"
```
Expected: ImportError

- [ ] **Step 3: Implement `precompute_ocr_results` trong `orchestrator/video_process.py`**

Thêm sau `apply_temporal_inpaint`:

```python
def precompute_ocr_results(
    input_path: str,
    total_frames: int,
    fps: float,
    ocr_fps: float,
    ocr_batch_size: int,
    width: int,
    height: int,
    ocr,
) -> dict[int, list[tuple]]:
    """
    Pre-pass: gọi PaddleOCR theo batch trên các OCR frames.
    Trả về dict {frame_index: list of (x,y,w,h) boxes}.
    """
    frame_skip = max(1, int(fps / ocr_fps))
    ocr_indices = list(range(0, total_frames, frame_skip))

    results: dict[int, list[tuple]] = {}
    batch_smalls: list = []
    batch_scales: list = []
    batch_frame_indices: list[int] = []

    cap = cv2.VideoCapture(input_path)

    def _flush_batch():
        if not batch_smalls:
            return
        with _ocr_lock:
            ocr_results = ocr.ocr(batch_smalls, cls=False)
        for i, fi in enumerate(batch_frame_indices):
            results[fi] = _parse_ocr_boxes(ocr_results[i], batch_scales[i], width, height)
        batch_smalls.clear()
        batch_scales.clear()
        batch_frame_indices.clear()

    for fi in ocr_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        small, scale = _scale_frame_for_ocr(frame)
        batch_smalls.append(small)
        batch_scales.append(scale)
        batch_frame_indices.append(fi)

        if len(batch_smalls) >= ocr_batch_size:
            _flush_batch()

    _flush_batch()  # flush cuối
    cap.release()
    return results
```

- [ ] **Step 4: Chạy tests**

```
python -m pytest tests/test_video_process.py -v -k "precompute_ocr"
```
Expected: 2 tests PASS

- [ ] **Step 5: Full suite**

```
python -m pytest tests/ -v
```
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/video_process.py tests/test_video_process.py
git commit -m "feat(video_process): add precompute_ocr_results — batch OCR pre-pass"
```

---

## Task 5: Integrate vào `remove_watermark_from_video()` + Mở rộng `_detect_static_boxes`

**Files:**
- Modify: `orchestrator/video_process.py`

**Thay đổi:**
1. `_detect_static_boxes`: nhận `total_frames` → sample 30 frames đều toàn video
2. `remove_watermark_from_video`: gọi `build_temporal_reference()` + `precompute_ocr_results()` trước pipeline; OCR thread dùng dict lookup; inpaint thread dùng `apply_temporal_inpaint()`

---

- [ ] **Step 1: Sửa `_detect_static_boxes` — 30 frames đều toàn video**

Thay toàn bộ function `_detect_static_boxes`:

```python
STATIC_SCAN_FRAMES = 30
STATIC_THRESHOLD = 0.7

def _detect_static_boxes(input_path: str, ocr, fps: float, width: int, height: int, total_frames: int) -> list[tuple]:
    """Scan 30 frames phân bố đều toàn video để tìm watermark tĩnh."""
    n = min(STATIC_SCAN_FRAMES, max(3, total_frames))
    indices = [int(i * (total_frames - 1) / (n - 1)) for i in range(n)]

    box_counts: dict = {}
    box_map: dict = {}
    scanned = 0

    cap = cv2.VideoCapture(input_path)
    for fi in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        small, scale = _scale_frame_for_ocr(frame)
        with _ocr_lock:
            result = ocr.ocr(small, cls=False)
        boxes = _parse_ocr_boxes(result, scale, width, height)
        for box in boxes:
            x, y, w, h = box
            key = (x // 20, y // 20)
            box_counts[key] = box_counts.get(key, 0) + 1
            box_map[key] = box
        scanned += 1
    cap.release()

    threshold = max(1, int(scanned * STATIC_THRESHOLD))
    return [box_map[k] for k, cnt in box_counts.items() if cnt >= threshold]
```

- [ ] **Step 2: Integrate pre-passes vào `remove_watermark_from_video()`**

Trong `remove_watermark_from_video`, sau khi lấy `total_frames`, `fps`, `width`, `height`:

**Thay** block `cap_scan / _detect_static_boxes` cũ bằng:
```python
    ocr = get_ocr_instance()

    # --- Pre-pass A: detect static watermark boxes (30 frames đều video) ---
    print(f"[VideoProcess] Quét {STATIC_SCAN_FRAMES} frames toàn video để tìm watermark tĩnh...")
    try:
        static_boxes = _detect_static_boxes(input_path, ocr, fps, width, height, total_frames)
    except Exception as e:
        print(f"[VideoProcess] Cảnh báo static scan: {e}")
        static_boxes = []
    print(f"[VideoProcess] Phát hiện {len(static_boxes)} static box(es).")

    # --- Pre-pass B: temporal reference (clean background) ---
    print("[VideoProcess] Xây dựng temporal reference...")
    try:
        temporal_ref = build_temporal_reference(input_path, n_samples=20)
        if temporal_ref is None:
            print("[VideoProcess] Video quá ngắn, dùng TELEA fallback.")
    except Exception as e:
        print(f"[VideoProcess] Cảnh báo temporal reference: {e}")
        temporal_ref = None

    # --- Pre-pass C: OCR batch pre-computation ---
    if not mask_only:
        print(f"[VideoProcess] Pre-compute OCR theo batch (batch_size={_ocr_batch_size})...")
        try:
            ocr_lookup = precompute_ocr_results(
                input_path, total_frames, fps, _ocr_fps, _ocr_batch_size,
                width, height, ocr
            )
        except Exception as e:
            print(f"[VideoProcess] Cảnh báo OCR precompute: {e}")
            ocr_lookup = {}
    else:
        ocr_lookup = {}
```

- [ ] **Step 3: Sửa `ocr_thread` — dùng dict lookup**

Thay `ocr_thread` function:
```python
    def ocr_thread():
        try:
            frame_skip = max(1, int(fps / _ocr_fps))
            cached: list = []
            idx = 0
            while True:
                frame = read_q.get()
                if frame is SENTINEL:
                    break
                if idx in ocr_lookup:
                    cached = ocr_lookup[idx]
                ocr_q.put((frame, cached, idx))
                idx += 1
        except Exception as e:
            error_q.put(e)
        finally:
            ocr_q.put(SENTINEL)
```

- [ ] **Step 4: Sửa `inpaint_thread` — dùng `apply_temporal_inpaint`**

Thay `inpaint_thread` function:
```python
    def inpaint_thread():
        try:
            while True:
                item = ocr_q.get()
                if item is SENTINEL:
                    break
                frame, dynamic_boxes, idx = item
                if mask_only:
                    all_boxes = list(static_boxes) + list(dynamic_boxes)
                    if all_boxes:
                        frame = apply_inpaint_to_frame(frame, all_boxes, mask_only=True)
                else:
                    if static_boxes or dynamic_boxes:
                        frame = apply_temporal_inpaint(frame, temporal_ref, static_boxes, dynamic_boxes)
                write_q.put(frame)

                if idx > 0 and idx % max(1, int(fps) * 5) == 0:
                    print(f"[VideoProcess] Đã xử lý {idx}/{total_frames} frames...")
        except Exception as e:
            error_q.put(e)
        finally:
            write_q.put(SENTINEL)
```

- [ ] **Step 5: Chạy full test suite**

```
python -m pytest tests/ -v
```
Expected: tất cả PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/video_process.py
git commit -m "feat(video_process): integrate temporal inpainting + OCR batch pre-pass into pipeline"
```

---

## Task 6: Wire `video_ocr.py` + Integration Test

**Files:**
- Modify: `orchestrator/stages/video_ocr.py`
- Modify: `tests/test_video_process.py`

**Interfaces:**
- Consumes: signature mới `remove_watermark_from_video(..., settings=None)`

---

- [ ] **Step 1: Cập nhật calls trong `video_ocr.py`**

Thay 2 dòng gọi `remove_watermark_from_video`:
```python
# Trước:
await asyncio.to_thread(remove_watermark_from_video, input_video, mask_video, True)
await asyncio.to_thread(remove_watermark_from_video, input_video, output_video, False)

# Sau:
await asyncio.to_thread(remove_watermark_from_video, input_video, mask_video, True, settings)
await asyncio.to_thread(remove_watermark_from_video, input_video, output_video, False, settings)
```

- [ ] **Step 2: Thêm integration test vào `tests/test_video_process.py`**

```python
def test_remove_watermark_integration_creates_output():
    """remove_watermark_from_video chạy end-to-end không crash."""
    import tempfile, os
    from orchestrator.video_process import remove_watermark_from_video
    from unittest.mock import patch, MagicMock

    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as fin:
        in_path = fin.name
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as fout:
        out_path = fout.name

    try:
        _make_test_video(in_path, n_frames=30, h=50, w=50)

        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.return_value = []  # không phát hiện box nào

        with patch('orchestrator.video_process.get_ocr_instance', return_value=mock_ocr_instance), \
             patch('orchestrator.video_process._check_nvenc_cached', return_value=False):
            remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)

        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0
    finally:
        for p in [in_path, out_path]:
            if os.path.exists(p):
                os.unlink(p)
```

- [ ] **Step 3: Chạy integration test**

```
python -m pytest tests/test_video_process.py::test_remove_watermark_integration_creates_output -v
```
Expected: PASS

- [ ] **Step 4: Chạy full test suite**

```
python -m pytest tests/ -v
```
Expected: tất cả PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/stages/video_ocr.py tests/test_video_process.py
git commit -m "feat(video_ocr): pass settings to remove_watermark_from_video; add integration test"
```

---

## Checklist tự review

- [x] `build_temporal_reference` — Task 2 ✓
- [x] `apply_temporal_inpaint` — Task 3 ✓
- [x] `precompute_ocr_results` — Task 4 ✓
- [x] `_detect_static_boxes` 30-frame — Task 5 ✓
- [x] `ocr_fps` từ settings — Task 1 ✓
- [x] `ocr_batch_size` config — Task 1 ✓
- [x] nvenc cache — Task 1 ✓
- [x] `video_ocr.py` pass settings — Task 6 ✓
- [x] Tất cả function signatures nhất quán giữa các task ✓
- [x] Không có TBD/TODO ✓
- [x] Backward compat (`settings=None`) — Task 1, Task 5, Task 6 ✓
