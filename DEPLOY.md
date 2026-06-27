# Triển khai trên máy GPU & chẩn đoán lỗi

Runbook cho lần triển khai đầu trên máy có NVIDIA GPU (16–24 GB VRAM). Tập trung vào **build cục bộ** `whisperx` + `tts` (GPT-SoVITS) và cách đọc log để fix lỗi.

---

## 1. Chuẩn bị

```bash
# Kiểm tra GPU nhìn thấy trong Docker
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi

# Tạo .env (xem bảng biến môi trường trong README)
cp .env.example .env 2>/dev/null || touch .env
```

Bật DEBUG log toàn hệ thống khi cần:
```bash
echo "LOG_LEVEL=DEBUG" >> .env
```

---

## 2. Build các service cục bộ

`whisperx` và `tts` **không có trên Docker Hub** — compose tự build từ `./whisperx-service/` và `./tts-service/`.

```bash
# Build trước (xem log build để bắt lỗi pip/clone sớm)
docker compose build whisperx
docker compose --profile gpt_sovits build tts     # chỉ khi dùng GPT-SoVITS

# Hoặc build tất cả
docker compose build
```

Build lần đầu tải image CUDA + torch (~5–10 GB mỗi service) → mất 10–30 phút tùy mạng.

---

## 3. Khởi động & theo dõi log

```bash
# Mặc định (OmniVoice TTS) — whisperx bắt buộc, tts KHÔNG chạy
docker compose up -d
docker compose logs -f whisperx orchestrator

# Dùng GPT-SoVITS thay OmniVoice
TTS_ENGINE=gpt_sovits docker compose --profile gpt_sovits up -d
docker compose logs -f tts
```

Log mỗi service đã được ghi đầy đủ: startup (device/VRAM/model), từng request, và **traceback đầy đủ** khi lỗi.

---

## 4. Health check

```bash
curl http://localhost:8001/health     # whisperx  -> {"status":"ok","device":"cuda",...}
curl http://localhost:9880/health     # tts       -> {"integration_import_ok": true/false}
curl http://localhost:3900/health     # omnivoice
curl http://localhost:8000/api/videos # orchestrator
```

`tts` `/health` trả `integration_import_ok` — nếu `false`, xem mục 5.3.

---

## 5. Lỗi thường gặp & cách fix

### 5.1 WhisperX — `CUDA not available` trong log
- Log in `device=cpu` + cảnh báo. Nguyên nhân: Docker không thấy GPU.
- Fix: cài `nvidia-container-toolkit`, kiểm tra `docker run --gpus all ... nvidia-smi`.

### 5.2 WhisperX — alignment/diarization failed (traceback warning)
- Không chặn pipeline: segment vẫn trả về (alignment thô, `speaker=null`).
- Diarization cần `HF_TOKEN` hợp lệ + đã chấp nhận điều khoản model `pyannote/speaker-diarization` trên HuggingFace.
- Fix: `echo "HF_TOKEN=hf_xxx" >> .env && docker compose restart whisperx`.

### 5.3 TTS — `integration_import_ok: false` / `tts failed` khi gọi /tts
- **Đây là điểm tích hợp duy nhất.** Log boot in traceback của import `GPT_SoVITS.inference_webui.get_tts_wav`.
- Nguyên nhân thường gặp:
  - Revision GPT-SoVITS đã clone đổi tên/đường dẫn `get_tts_wav`.
  - Thiếu model weights trong `models/tts/` (mount vào `/app/GPT-SoVITS/GPT_SoVITS/pretrained_models`).
- Fix: vào container kiểm tra layout thực tế rồi sửa import trong `tts-service/app.py::synthesize_wav`:
  ```bash
  docker compose exec tts python -c "import sys; sys.path.insert(0,'/app/GPT-SoVITS'); import GPT_SoVITS.inference_webui as m; print([x for x in dir(m) if 'tts' in x.lower()])"
  ```

### 5.4 Service không healthy sau start_period
```bash
docker compose ps                 # xem cột STATUS / health
docker compose logs whisperx      # đọc traceback
docker compose restart whisperx
```

### 5.5 CUDA out of memory
- Hạ tải đồng thời: dùng `VRAM_PROFILE=16gb`, hoặc whisper model nhỏ hơn:
  ```bash
  echo "WHISPER_MODEL=large-v2" >> .env   # hoặc medium / small
  docker compose restart whisperx
  ```

### 5.6 Build TTS fail ở bước `git clone` hoặc `pip install`
- Mạng chặn GitHub / PyPI. Build lại: `docker compose build --no-cache tts`.
- Pin revision khác: sửa dòng `git clone` trong `tts-service/Dockerfile`.

---

## 6. Thu thập log để báo lỗi

```bash
docker compose logs --no-color > deploy-logs.txt
docker compose ps >> deploy-logs.txt
```

Gửi `deploy-logs.txt` kèm mô tả bước đang chạy khi lỗi.
