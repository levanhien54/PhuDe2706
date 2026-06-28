# GPU Image Processing Optimization — Design Spec
**Date:** 2026-06-28  
**Target hardware:** RTX 3090 / 4090 (24GB VRAM)  
**Goal:** Tăng tốc + tăng chất lượng watermark removal trong video dubbing pipeline

---

## 1. Context & Bottlenecks

Pipeline hiện tại (`orchestrator/video_process.py`) chạy một 4-thread pipeline:
`Reader → OCR Thread → Inpaint Thread → Writer`

Hai bottleneck chính trên 24GB GPU:

| Bottleneck | Vị trí | Impact |
|---|---|---|
| `cv2.INPAINT_TELEA` CPU trên mỗi frame | `apply_inpaint_to_frame()` line 147 | GPU 24GB nhàn rỗi trong suốt giai đoạn này |
| PaddleOCR gọi 1 frame/lần | `ocr_thread()` line 276 | Bỏ qua batch inference của PaddleOCR |

Vấn đề phụ:
- `ocr_fps = 2.0` hardcode tại line 238 (không đọc từ `settings.ocr_fps`)
- Static watermark scan chỉ 10 frames đầu → miss logo xuất hiện giữa/cuối video
- `check_nvenc()` gọi subprocess mỗi lần tạo `FFmpegWriter`

---

## 2. Approach: Temporal Reference Inpainting + OCR Batching

### 2.1 Temporal Reference (core change)

Thêm **precompute pass** ngắn trước pipeline chính:

```
[Pass 0] build_temporal_reference(input_path, n_samples=20)
         → Sample 20 frames đều toàn video
         → Tính pixel-wise median → "clean background" numpy array
         → ~3–5s cho 1080p, stored in-memory

[Pass 1] remove_watermark_from_video() — 4-thread pipeline giữ nguyên
         → static_boxes: copy pixels từ temporal_reference   (O(n_pixels), fast)
         → dynamic_boxes: TELEA như cũ                       (fallback)
         → no boxes: pass-through
```

**Tại sao median hoạt động:** watermark che một phần nhỏ frame. Các frames khác có nền thật ở đúng vị trí đó. Median 20 frames = nền thật, không bị ảnh hưởng bởi watermark hay chuyển động ngắn.

**Giới hạn:** không tối ưu khi camera pan liên tục (dynamic boxes). Dynamic boxes vẫn dùng TELEA — không regression.

### 2.2 OCR Batching

```python
# Trước: 1 frame/call
result = ocr.ocr(small_frame, cls=False)

# Sau: buffer 4 frames → 1 call
results = ocr.ocr([f1, f2, f3, f4], cls=False)
```

- Buffer size = `settings.ocr_batch_size` (default: 4)
- Flush khi hết stream với số frames còn lại < batch_size
- Mỗi frame vẫn nhận đúng boxes của nó (index tracking)

### 2.3 Static Scan Mở Rộng

```
Trước: 10 frames đầu video
Sau:   30 frames, sample đều — 10 frames đầu + 10 frames giữa + 10 frames cuối
```

Phát hiện logo/watermark xuất hiện muộn (rất phổ biến với channel watermark).

### 2.4 Config Fixes

- `ocr_fps`: đọc từ `settings.ocr_fps` thay vì hardcode `2.0`
- `check_nvenc()`: cache kết quả ở module-level `_NVENC_AVAILABLE`
- Interface `remove_watermark_from_video()` nhận thêm param `settings=None`

---

## 3. Files Thay Đổi

| File | Thay đổi |
|---|---|
| `orchestrator/video_process.py` | Thêm `build_temporal_reference()`, `apply_temporal_inpaint()`, OCR batching trong `ocr_thread`, cache nvenc, static scan 30 frames, param `settings` |
| `orchestrator/stages/video_ocr.py` | Pass `settings` vào `remove_watermark_from_video()` |
| `orchestrator/config.py` | Thêm `ocr_batch_size: int = Field(4, validation_alias="OCR_BATCH_SIZE")` |
| `tests/test_video_process.py` | Tests mới cho temporal reference, temporal inpaint, OCR batching |

**Không thay đổi:** VRAMManager, pipeline.py, threading architecture, TELEA fallback.

---

## 4. New Functions

### `build_temporal_reference(input_path, n_samples=20) -> np.ndarray | None`
- Mở video, sample `n_samples` frames phân bổ đều
- Nếu video < 3 frames: return `None` (fallback về TELEA)
- Stack frames → `np.median(stack, axis=0).astype(np.uint8)`
- Return array shape `(H, W, 3)`

### `apply_temporal_inpaint(frame, reference, static_boxes, dynamic_boxes) -> np.ndarray`
- `reference is None` → dùng TELEA cho tất cả boxes (backward compat)
- `static_boxes`: `frame[y:y+h, x:x+w] = reference[y:y+h, x:x+w]`
- `dynamic_boxes`: gọi `cv2.inpaint()` như cũ
- Return frame đã xử lý

---

## 5. Error Handling

| Situation | Behavior |
|---|---|
| `build_temporal_reference` thất bại | Log warning, `temporal_ref = None`, toàn bộ video dùng TELEA |
| Video < 3 frames | `temporal_ref = None`, fallback TELEA |
| OCR batch flush (frames còn lại < batch_size) | Flush với số frames thực tế |
| `settings=None` | Dùng hardcoded defaults (backward compatible) |
| Static + dynamic boxes overlap | Temporal có priority (overwrite sau TELEA) |

---

## 6. Testing Strategy

| Test | Verify |
|---|---|
| `test_build_temporal_reference` | Trả về ndarray shape đúng; handle video ngắn (< 3 frames) |
| `test_apply_temporal_inpaint_static` | Pixels trong static_boxes == pixels từ reference |
| `test_apply_temporal_inpaint_fallback` | `reference=None` → không crash, dùng TELEA |
| `test_ocr_batch_calls` | Mock PaddleOCR: batch call đúng = `ceil(n_frames / batch_size)` |
| `test_config_ocr_batch_size` | Default = 4, overrideable qua `OCR_BATCH_SIZE` env var |

Tests dùng synthetic numpy frames — không cần video file thật, không cần GPU.

---

## 7. Expected Improvements

| Metric | Trước | Sau (estimate) |
|---|---|---|
| Inpainting time/frame (static watermark) | ~15ms (TELEA CPU) | ~0.1ms (pixel copy) |
| OCR calls cho 1000 frames @ 2fps, batch=4 | 500 calls | ~125 calls |
| Static scan coverage | 10 frames đầu | 30 frames toàn video |
| Watermark miss rate (mid-video logos) | Cao | Thấp |
