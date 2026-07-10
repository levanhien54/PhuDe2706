# Tối ưu hiệu năng & kiểm chứng (GPU 24GB)

Tài liệu này gom tất cả **núm chỉnh hiệu năng** (env / `.env`) và **checklist kiểm chứng trên
máy đích** sau đợt tối ưu 10/07/2026 (nhánh `feat/deployment-packaging`). Mục tiêu: nhanh nhất
mà vẫn giữ chất lượng trên GPU NVIDIA 24GB; GPU 16GB được tự hạ (clamp) về mức an toàn.

---

## 1. Tự động theo VRAM_PROFILE

`setup_native.ps1` ghi `VRAM_PROFILE` vào `.env` theo GPU phát hiện (24gb cho card ≥24GB, 16gb
cho card 16–23GB). `run_native.ps1` dùng nó để:

- **24gb**: bật các mức nhanh (4 TTS replica, 4 Ollama slot, WhisperX batch 64, OCR_BATCH 48,
  ProPainter subvideo 200).
- **16gb**: **tự clamp** `OMNIVOICE_REPLICAS`/`TTS_CONCURRENCY` về 2 và `WHISPER_BATCH_SIZE` về 32
  (tránh OOM). Giá trị phi số (vd `auto`) được bỏ qua, không làm crash launcher.

---

## 2. Bảng núm chỉnh chính

| Biến (.env / env) | Mặc định | 16GB (clamp) | Ý nghĩa |
|---|---|---|---|
| `VRAM_PROFILE` | `24gb` | `16gb` | Chọn hồ sơ phần cứng; điều khiển các clamp bên dưới. |
| `LLM_NUM_CTX` | `8192` | 8192 | Cửa sổ ngữ cảnh Ollama. **Quan trọng:** mặc định Ollama (2048) quá nhỏ → batch dịch bị cắt → chậm gấp bội. |
| `LLM_CONCURRENCY` | `4` | 4 | Số chunk dịch gửi song song. |
| `OLLAMA_NUM_PARALLEL` | `4` | 4 | Số request Ollama xử lý song song (phải ≥ LLM_CONCURRENCY). |
| `OMNIVOICE_REPLICAS` | `4` | `2` | Số bản sao model TTS (mỗi ~3GB). |
| `TTS_CONCURRENCY` | `4` | `2` | Số request TTS song song (giữ BẰNG replicas). |
| `WHISPER_BATCH_SIZE` | `64` | `32` | Batch giải mã WhisperX. |
| `OMNIVOICE_NUM_STEP` | `64` | 64 | Số bước diffusion TTS. Cao = chất lượng hơn, chậm hơn. FAST_MODE hạ về 32. |
| `DEMUCS_MODEL` | `htdemucs_ft` | như 24gb | Model tách nhạc. `htdemucs_ft` (4 model, SDR tốt) hoặc `htdemucs` (1 model, ~4x nhanh). FAST_MODE chọn `htdemucs`. |
| `OCR_BATCH` | 16 (48 khi 24gb) | 16 | Batch OCR CRAFT (chỉ khi bật OCR). |
| `OCR_MAX_H` | `480` | 480 | Chiều cao khung để OCR. Đặt `720` trên 24GB để bắt phụ đề nhỏ tốt hơn (chậm hơn). |
| `PROPAINTER_SUBVIDEO_LENGTH` | 80 (200 khi 24gb) | 80 | Độ dài đoạn ProPainter (chỉ khi bật). Dài hơn = ít pass = nhanh hơn. |
| `FAST_MODE` | `0` | — | Xem mục 3. |
| `WHISPERX_ENABLE_CUDNN` | `0` | — | Xem mục 4. |

> Giá trị đặt **tường minh** trong `.env` luôn được tôn trọng; các mức "24gb/16gb" chỉ là mặc định
> khi bạn không đặt.

---

## 3. FAST_MODE — công tắc tốc độ

Đặt `FAST_MODE=1` trong `.env` (rồi chạy lại `run_native.ps1`) để ưu tiên **tốc độ**:

- `OMNIVOICE_NUM_STEP` → **32** (TTS nhanh ~2x, phát âm kém tự nhiên hơn chút).
- `DEMUCS_MODEL` → **htdemucs** (tách nhạc nhanh ~4x, SDR thấp hơn chút).

Mặc định `FAST_MODE=0` = **chất lượng cao**. `setup_native.ps1` tải sẵn CẢ hai model Demucs nên
FAST_MODE không phải tải lại lúc chạy.

---

## 4. cuDNN cho STT (opt-in)

`WHISPERX_ENABLE_CUDNN` mặc định **0** vì bản PyTorch cu118 kèm `cudnn64_9.dll` lỗi (crash nếu bật).
Trên máy đích có cudnn thật (wheel `nvidia-cudnn`), đặt `=1` để align/VAD nhanh ~1.5–3x. An toàn:
nếu không nạp được cudnn thật, dịch vụ tự giữ TẮT (hành vi cũ). **Chỉ bật sau khi xác nhận STT không crash.**

---

## 5. Checklist kiểm chứng trên máy đích (A/B)

Các thay đổi sau đã ship nhưng cần **nghe/nhìn/đo trên GPU 24GB thật** (máy dev 8GB không chạy được):

| Mục | Commit | Kiểm chứng |
|---|---|---|
| Audio master-once (bỏ nén 2 lần) | `6279abb` | Nghe: giọng có sạch/đỡ nén-pump hơn không. Nếu tệ hơn → revert commit. |
| ProPainter mask (thêm phụ đề động) | `eb623dc` | Bật ProPainter, xác nhận **phụ đề bị xoá** và mask khớp khung hình. |
| NVENC -cq cho blur OCR | `d068ced` | Bật OCR, xem chất lượng/kích thước file output. |
| cuDNN | `38d137c` | `WHISPERX_ENABLE_CUDNN=1`, chắc chắn STT không crash rồi mới dùng. |
| FAST_MODE | `4157a45` | `FAST_MODE=1` cảm nhận khác biệt tốc độ/chất lượng. |

### Đo speedup khâu dịch (LLM)

Nguyên nhân gốc "dịch chậm" đã sửa (num_ctx). Cách xác nhận:

1. **Xem log**: trước fix, video dài có nhiều cảnh báo `batch_translation_partial`,
   `single_translation_failed`, `batch_translation_failed_fallback`. Sau fix, các cảnh báo này
   gần như biến mất = batch không còn bị cắt.
2. **So thời gian**: orchestrator log `StageResult(stage="translate", duration_seconds=…)` — so
   cùng một video trước/sau, và thử `OLLAMA_NUM_PARALLEL=4` vs `2`.

---

Chi tiết từng commit + lý do các mục KHÔNG làm (keep-warm gây OOM, httpx pooling rủi ro loop):
xem lịch sử git nhánh `feat/deployment-packaging` và memory `pipeline-optimization-2026-07-10`.
