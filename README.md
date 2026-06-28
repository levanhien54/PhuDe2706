# Video Dubbing & Dịch thuật Tự động

Hệ thống dubbing video **100% offline** — tách âm, nhận diện giọng, dịch thuật LLM, clone giọng, đồng bộ khẩu hình, xuất video — tối ưu cho GPU 16–24 GB VRAM chạy hoàn toàn bằng Python Native (không sử dụng Docker).

---

## Yêu cầu hệ thống

| Thành phần | Tối thiểu | Khuyến nghị |
|---|---|---|
| GPU | NVIDIA 16 GB VRAM (RTX 4080) | 24 GB (RTX 3090/4090) |
| RAM | 32 GB | 64 GB |
| Ổ cứng | 50 GB trống | 100 GB SSD |
| OS | Windows 10/11 hoặc Ubuntu 22.04 | Windows 11 / Ubuntu 22.04 |
| Môi trường | Python 3.10+, Node.js, FFmpeg | — |

---

## Triển khai (máy mới)

### Windows

Mở **PowerShell** (có quyền Administrator nếu cần) và chạy:

```powershell
# Tải toàn bộ models, tạo Python venv và cài thư viện (~15-20 GB)
.\setup_native.ps1
```

### Linux / macOS

Mở **Terminal** và chạy:

```bash
chmod +x setup_native.sh run_native.sh
./setup_native.sh
```

Script sẽ tự động:
1. Kiểm tra Python, Node.js, FFmpeg.
2. Tạo Python Virtual Environment (`venv`) chung để tối ưu không gian đĩa.
3. Cài đặt PyTorch với CUDA.
4. Cài đặt thư viện Backend (WhisperX, TTS, Demucs) và Frontend (npm install).
5. Tải mô hình Demucs.

*Lưu ý:* Để chạy LLM nội bộ, bạn cần tải và cài đặt phần mềm [Ollama](https://ollama.com/) trực tiếp trên máy host và tải mô hình tương ứng (ví dụ: `ollama run qwen2.5:14b`).

---

## Chạy hệ thống

Hệ thống sử dụng các script tiện ích để khởi động tất cả dịch vụ trong background.

### Trên Windows
```powershell
.\run_native.ps1
```

### Trên Linux / macOS
```bash
./run_native.sh
```

Sau khi khởi chạy:
- Bỏ video `.mp4` vào thư mục `data/input/`
- Truy cập giao diện tại: **http://localhost:5173**
- Xem kết quả tại thư mục `data/output/`

---

## Triển khai Offline Siêu Tốc (Cho máy chủ không có Internet)

Nếu bạn cần đem bộ mã nguồn này triển khai trên một máy chủ (server) mới, mạng chậm hoặc bị tường lửa chặn, hãy dùng phương pháp Đóng gói Offline:

### Bước 1: Đóng gói trên máy đã cài đặt thành công
Trên máy tính hiện tại đã chạy ngon lành, mở PowerShell và chạy:
```powershell
.\pack_offline_bundle.ps1
```
*(Đối với Linux: `./pack_offline_bundle.sh`)*

Hệ thống sẽ tải toàn bộ các gói thư viện Python (bao gồm PyTorch 2.5GB) lưu vào thư mục `offline_wheels/`.

### Bước 2: Nén và Copy
- Nén toàn bộ thư mục `PhuDe27.06` thành một file `.zip`.
- **Lưu ý BỎ QUA:** Không nén thư mục `venv/` (vì khác máy sẽ bị lỗi đường dẫn), `data/input/`, `data/output/`.
- Copy file `.zip` này sang máy chủ mới và giải nén.

### Bước 3: Cài đặt siêu tốc trên máy chủ mới
Mở PowerShell tại máy chủ mới và chạy:
```powershell
.\setup_offline.ps1
```
*(Đối với Linux: `./setup_offline.sh`)*

Quá trình này sẽ sử dụng các tệp tin có sẵn trong `offline_wheels/` để cài đặt ngay lập tức (chỉ mất ~1-2 phút) mà không cần tải bất cứ thứ gì từ Internet.

---

## Cấu trúc thư mục

```
PhuDe27.06/
├── data/
│   ├── input/       ← Bỏ video .mp4 vào đây
│   ├── output/      ← Video đã dub xuất ra đây
│   └── temp/        ← File tạm (tự xóa sau khi xong)
├── models/
│   ├── ollama/      ← LLM weights (tự động qua phần mềm Ollama host)
│   ├── whisper/     ← Whisper Large-v3
│   ├── demucs/      ← Demucs htdemucs
│   ├── tts/         ← GPT-SoVITS models
│   ├── omnivoice/   ← OmniVoice models
│   └── lipsync/     ← LatentSync models
├── orchestrator/    ← Pipeline code
├── frontend/        ← Code UI
├── setup_native.ps1 ← Windows setup script
└── run_native.ps1   ← Windows run script
```

---

## Pipeline xử lý

```
VIDEO GỐC
  ├── [M2] Demucs     → tách vocal + nhạc nền (Chạy Local Subprocess)
  ├── [M7] PaddleOCR  → phát hiện + xóa chữ (Gaussian Blur)
  ├── [M3] WhisperX   → STT + word-level timestamps (FastAPI Local)
  ├── [M4] LLM        → dịch thuật tiếng Việt (Ollama Host)
  ├── [M5] GPT-SoVITS → clone giọng, sinh audio tiếng Việt
  ├── [M6] Rubberband → stretch audio khớp timestamps
  ├── [M9] LatentSync → đồng bộ khẩu hình (tùy chọn)
  └── [M10] FFmpeg    → mux audio + video → VIDEO THÀNH PHẨM
```

---

## Cấu hình Nâng cao (.env)

Hệ thống cho phép tinh chỉnh qua file `.env`. Dưới đây là một số biến quan trọng:

| Biến | Mặc định | Mô tả |
|---|---|---|
| `TTS_ENGINE` | `gpt_sovits` | `omnivoice` hoặc `gpt_sovits` |
| `LLM_BACKEND` | `ollama` | `ollama` hoặc `vllm`. *Khuyến cáo: vLLM tối ưu nhất cho Linux.* |
| `LLM_MODEL` | `qwen2.5:14b` | Tên model Ollama hoặc HuggingFace (nếu dùng vllm) |
| `VRAM_PROFILE` | `16gb` | `16gb` hoặc `24gb` để điều chỉnh ngưỡng bộ nhớ |
| `ENABLE_LIPSYNC` | `false` | Bật/tắt đồng bộ môi (LatentSync) |
| `ENABLE_PROPAINTER` | `false` | Bật/tắt xoá chữ bằng Deep Learning (chất lượng cao nhưng chậm) |
| `ENABLE_CPU_OFFLOAD` | `false` | Bật/tắt offload weights CPU (NEO) để giảm tải VRAM |
| `ENABLE_KVCACHED` | `false` | Bật/tắt KV Cache linh hoạt cho môi trường nghẽn VRAM |
| `LOG_LEVEL` | `INFO` | Mức độ log (`DEBUG` / `INFO`) |

---

## Khắc phục lỗi thường gặp

**Lỗi CUDA out of memory:**
- Nếu bạn có GPU 16GB, cần đảm bảo chỉnh cấu hình trong `.env`:
  `VRAM_PROFILE=16gb`

**Thay đổi Port/API:**
- Các cấu hình API được định tuyến qua `orchestrator/config.py` và sử dụng `http://127.0.0.1:xxx` thay vì Docker DNS. Bạn có thể thay đổi cổng trong file `run_native` nếu bị xung đột.
