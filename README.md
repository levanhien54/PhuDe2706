# Video Dubbing & Dịch thuật Tự động

Hệ thống dubbing video **100% offline** — tách âm, nhận diện giọng, dịch thuật LLM, clone giọng, đồng bộ khẩu hình, xuất video — tối ưu cho GPU 16–24 GB VRAM.

---

## Yêu cầu hệ thống

| Thành phần | Tối thiểu | Khuyến nghị |
|---|---|---|
| GPU | NVIDIA 16 GB VRAM (RTX 4080) | 24 GB (RTX 3090/4090) |
| RAM | 32 GB | 64 GB |
| Ổ cứng | 50 GB trống | 100 GB SSD |
| OS | Windows 10/11 hoặc Ubuntu 22.04 | Ubuntu 22.04 |
| Docker | Docker Desktop 4.x + GPU support | — |

---

## Triển khai lần đầu (máy mới)

### Windows

```powershell
# Tải toàn bộ models (~20 GB) và cấu hình tự động
.\setup.ps1

# Tùy chọn:
.\setup.ps1 -LlmModel "qwen2.5:14b" -VramProfile "16gb"
.\setup.ps1 -LlmModel "gemma2:27b"  -VramProfile "24gb" -WithLipsync
```

### Linux / macOS

```bash
bash setup.sh

# Tùy chọn:
bash setup.sh --llm-model qwen2.5:14b --vram 16gb
bash setup.sh --llm-model gemma2:27b  --vram 24gb --with-lipsync
```

Script sẽ tự động:
1. Kiểm tra Docker + NVIDIA GPU
2. Tạo `.env` từ mẫu
3. Pull tất cả Docker images
4. Tải LLM model vào `models/ollama/`
5. Tải Whisper Large-v3 vào `models/whisper/`
6. Tải Demucs htdemucs vào `models/demucs/`
7. Tải OmniVoice vào `models/omnivoice/`

---

## Chuyển máy / Backup models

Để chuyển sang máy khác **không cần tải lại**:

```
# Copy toàn bộ thư mục models/ sang máy mới
rsync -av --progress models/ user@new-machine:/path/to/project/models/

# Hoặc nén lại
tar -czf models-backup.tar.gz models/
```

Trên máy mới, chỉ cần chạy:
```bash
# Bỏ qua bước pull models (đã có sẵn)
bash setup.sh --skip-pull
docker compose up
```

---

## Chạy hệ thống

```bash
# 1. Bỏ video .mp4 vào thư mục input
cp my_video.mp4 data/input/

# 2. Khởi động hệ thống
docker compose up

# 3. Xem kết quả
ls data/output/
```

> **Lưu ý build cục bộ:** `whisperx` và `tts` (GPT-SoVITS) **không có image sẵn trên Docker Hub** — chúng được build cục bộ từ `./whisperx-service/` và `./tts-service/` khi chạy `docker compose up` (compose tự build lần đầu). WhisperX là bắt buộc; GPT-SoVITS chỉ build khi bật profile `gpt_sovits`.

### TTS bằng GPT-SoVITS thay vì OmniVoice

Mặc định dùng OmniVoice. Để dùng GPT-SoVITS (cần đặt model vào `models/tts/`):

```bash
TTS_ENGINE=gpt_sovits docker compose --profile gpt_sovits up
```

### Phân tách người nói (speaker diarization) cho WhisperX

Tùy chọn — cần HuggingFace token (pyannote). Không có token thì bỏ qua, mọi segment có `speaker=null`:

```bash
echo "HF_TOKEN=hf_xxxxx" >> .env
```

### Với Lip-sync (LatentSync, cần build image trước)

```bash
# Build LatentSync image
docker build -t lipsync-api:latest ./lipsync-service/

# Chạy với lip-sync
ENABLE_LIPSYNC=true docker compose --profile lipsync up
```

---

## Cấu hình qua biến môi trường

Chỉnh file `.env`:

| Biến | Mặc định | Mô tả |
|---|---|---|
| `TTS_ENGINE` | `omnivoice` | `omnivoice` hoặc `gpt_sovits` |
| `LLM_BACKEND` | `ollama` | `ollama` hoặc `vllm` |
| `LLM_MODEL` | `qwen2.5:14b` | Tên model Ollama |
| `VRAM_PROFILE` | `16gb` | `16gb` hoặc `24gb` |
| `ENABLE_LIPSYNC` | `false` | `true` để bật LatentSync |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

---

## Cấu trúc thư mục

```
PhuDe27.06/
├── data/
│   ├── input/       ← Bỏ video .mp4 vào đây
│   ├── output/      ← Video đã dub xuất ra đây
│   └── temp/        ← File tạm (tự xóa sau khi xong)
├── models/
│   ├── ollama/      ← LLM weights (qwen2.5, gemma2...)
│   ├── whisper/     ← Whisper Large-v3
│   ├── demucs/      ← Demucs htdemucs
│   ├── tts/         ← GPT-SoVITS models
│   ├── omnivoice/   ← OmniVoice models
│   └── lipsync/     ← LatentSync models
├── orchestrator/    ← Pipeline code
├── docker-compose.yml
├── setup.ps1        ← Windows setup
└── setup.sh         ← Linux/macOS setup
```

---

## Pipeline xử lý

```
VIDEO GỐC
  ├── [M2] Demucs     → tách vocal + nhạc nền
  ├── [M7] PaddleOCR  → phát hiện + xóa chữ (Gaussian Blur)
  ├── [M3] WhisperX   → STT + word-level timestamps
  ├── [M4] LLM        → dịch thuật tiếng Việt (Qwen / Gemma)
  ├── [M5] OmniVoice  → clone giọng, sinh audio tiếng Việt
  ├── [M6] Rubberband → stretch audio khớp timestamps
  ├── [M9] LatentSync → đồng bộ khẩu hình (tùy chọn)
  └── [M10] FFmpeg    → mux audio + video → VIDEO THÀNH PHẨM
```

---

## Khắc phục lỗi thường gặp

**Lỗi CUDA out of memory:**
```bash
# Chỉnh VRAM profile xuống
echo "VRAM_PROFILE=16gb" >> .env
docker compose restart orchestrator
```

**Service không healthy sau 2 phút:**
```bash
docker compose logs whisperx   # xem log
docker compose restart whisperx
```

**Ollama không tải được model:**
```bash
docker exec ai_dubbing_ollama ollama pull qwen2.5:14b
```

**Xem log pipeline:**
```bash
docker compose logs -f orchestrator
```
