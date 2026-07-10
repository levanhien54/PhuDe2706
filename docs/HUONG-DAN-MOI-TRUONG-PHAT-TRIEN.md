# Hướng dẫn cấu hình môi trường phát triển đầy đủ

Tài liệu này hướng dẫn dựng **môi trường phát triển hoàn chỉnh** cho hệ thống Video
Dubbing — từ một máy Windows trống đến chỗ chạy được toàn bộ pipeline từ mã nguồn, và
(tuỳ chọn) đóng gói ra bộ cài `Setup.exe + app.7z` để phát hành.

> Đối tượng: lập trình viên / người vận hành dựng máy để **chạy từ nguồn** và **kiểm thử**.
> Nếu bạn chỉ cần cài bản đóng gói sẵn cho người dùng cuối, xem `HUONG-DAN/01-CAI-DAT.md`.
>
> ⚡ **Tối ưu hiệu năng** (các núm FAST_MODE / VRAM_PROFILE / cuDNN…) + **checklist kiểm chứng
> trên GPU 24GB**: xem [TOI-UU-HIEU-NANG.md](TOI-UU-HIEU-NANG.md).

---

## 0. Hai chế độ làm việc

| Chế độ | Mục đích | Script chính | Yêu cầu Internet |
|---|---|---|---|
| **Chạy từ nguồn (dev)** | Phát triển + kiểm thử pipeline | `setup_native.ps1` → `run_native.ps1` | Có (tự tải model + phụ thuộc) |
| **Đóng gói phát hành** | Tạo `Setup.exe + app.7z` cho máy đích | `build_deploy_bundle.ps1` | Có (khi dựng lần đầu) |

Trình cài **online** `setup_native.ps1` sẽ **tự động**: kiểm tra phần cứng → tải PyTorch
(CUDA 11.8), WhisperX, OmniVoice, Ollama + model dịch, Demucs, FFmpeg → tạo `.env`. Bạn chỉ
cần cài trước một số phần mềm hệ thống ở mục 2.

---

## 1. Yêu cầu phần cứng

| Thành phần | Tối thiểu | Ghi chú |
|---|---|---|
| GPU | NVIDIA, **≥ 16 GB VRAM** | RTX 4080/3090/4090. **Bắt buộc NVIDIA** — không hỗ trợ AMD/Intel. Cổng kiểm tra sẽ CHẶN cài nếu < 16 GB. |
| Driver GPU | **≥ 452.39** | Cần cho CUDA 11.8. Cũ hơn chỉ cảnh báo, nên cập nhật. |
| RAM | 32 GB (khuyến nghị 64 GB) | Video dài cần nhiều RAM hơn. |
| Ổ đĩa trống | **≥ 35 GB** để chạy dev; **~55 GB** nếu đóng gói | Model + venv + runtime. |
| OS | Windows 10/11 64-bit | Bộ cài + cổng kiểm tra phần cứng là Windows-only. Chạy-từ-nguồn trên Linux dùng `setup_native.sh` (chưa có cổng kiểm tra). |

---

## 2. Phần mềm hệ thống cần cài TRƯỚC (thủ công)

Các phần này `setup_native.ps1` **không tự cài** (cần trình cài hệ thống). Cài xong hãy **mở
lại cửa sổ PowerShell** để cập nhật PATH.

| Phần mềm | Phiên bản | Nguồn / ghi chú |
|---|---|---|
| **Python** | **3.10.x** (khuyến nghị 3.10.11) | [python.org/downloads/release/python-31011](https://www.python.org/downloads/release/python-31011/) — bản Windows 64-bit, **tích "Add python.exe to PATH"**. Xem lưu ý ⚠️ bên dưới. |
| **Node.js** | LTS ≥ 18 | [nodejs.org](https://nodejs.org) — bản Windows 64-bit (cần cho giao diện + build Electron). |
| **Git** | mới nhất | [git-scm.com](https://git-scm.com) — cần để lấy mã nguồn và (tuỳ chọn) tải ProPainter/LatentSync. |
| Driver NVIDIA | ≥ 452.39 | [nvidia.com/drivers](https://www.nvidia.com/drivers). |

**KHÔNG cần cài tay** (script tự tải): FFmpeg, Ollama, và toàn bộ model/thư viện Python.

> ⚠️ **Về phiên bản Python — quan trọng:**
> - **Chạy dev từ nguồn:** Python **3.10 / 3.11 / 3.12** đều chạy được (3.11/3.12 chỉ cảnh báo).
> - **Đóng gói bản phát hành:** **BẮT BUỘC dùng Python 3.10.x** để tạo `venv`. Bộ cài ghép
>   `venv` với `python-runtime` (Python 3.10) trên máy đích; nếu `venv` được tạo bằng 3.11/3.12
>   thì các gói nhị phân (torch, ctranslate2…) sẽ lệch ABI và hỏng khi chạy trên máy đích.
> - Để an toàn cho cả hai: **cài Python 3.10.x và để nó là `python` trên PATH.**

---

## 3. Lấy mã nguồn

```powershell
git clone -b feat/deployment-packaging https://github.com/levanhien54/PhuDe2706 PhuDe2706
cd PhuDe2706
```

Nếu đã có sẵn thư mục:

```powershell
git fetch origin
git checkout feat/deployment-packaging
git pull
```

---

## 4. Cài môi trường tự động (ONLINE)

```powershell
.\setup_native.ps1
```

Trình cài chạy theo thứ tự:

1. **Cổng kiểm tra phần cứng & thành phần** — gộp tất cả vấn đề rồi báo một lần:
   - **CHẶN cài** (lỗi nặng): không có GPU NVIDIA, VRAM < 16 GB, đĩa < 35 GB, thiếu Python
     3.10–3.12, thiếu Node.js.
   - **Chỉ cảnh báo** (chạy tiếp): driver cũ, Python 3.11/3.12, thiếu Git, thiếu FFmpeg
     (sẽ tự tải).
   - Mỗi vấn đề in một dòng `-> Khắc phục:` kèm cách xử lý. Nếu có lỗi nặng, sửa xong rồi
     chạy lại `.\setup_native.ps1`.
2. **Tự tải FFmpeg** portable (nếu thiếu) vào `ffmpeg_extracted\`.
3. **Tạo `venv`** và cài **PyTorch CUDA 11.8** + phụ thuộc backend (WhisperX, TTS, OmniVoice,
   Demucs, vLLM tuỳ chọn, mmcv/ProPainter).
4. **Tải model:** Demucs (`htdemucs_ft`), WhisperX (`large-v3-turbo`), OmniVoice
   (`k2-fsa/OmniVoice`), và (nếu bật) ProPainter / LatentSync / GPT-SoVITS.
5. **Cài Ollama** (tự tải bản standalone nếu chưa có) và **`ollama pull qwen2.5:14b`** vào
   `models\ollama\models`.
6. **Tạo `.env`** từ `orchestrator\.env.example` và **ghi đúng `VRAM_PROFILE`** theo GPU đã
   phát hiện (`16gb` cho card 16 GB, `24gb` cho ≥ 24 GB).

### 4.1. Tuỳ biến trước khi chạy (tuỳ chọn)

Đặt biến môi trường trước khi gọi script để đổi lựa chọn engine/model:

```powershell
$env:WHISPER_MODEL   = "large-v3"        # thay cho large-v3-turbo (chậm hơn, WER thấp hơn chút)
$env:LLM_MODEL       = "qwen2.5:14b"     # model Ollama sẽ pull
$env:LIPSYNC_ENGINE  = "musetalk"        # tải thêm MuseTalk (mặc định latentsync)
$env:SEPARATION_ENGINE = "bs_roformer"   # cài audio-separator (mặc định demucs)
$env:TIMESTRETCH_ALGO  = "wsola"         # cài audiotsm (mặc định phasevocoder)
.\setup_native.ps1
```

### 4.2. Cài Offline (máy không có Internet)

Nếu máy đích không có mạng: trên một máy **đã cài thành công**, chạy `.\pack_offline_bundle.ps1`
để tải sẵn toàn bộ wheel Python vào `offline_wheels\`, chép cả dự án sang máy đích, rồi chạy:

```powershell
.\setup_offline.ps1
```

Lúc đó `setup_native.ps1`/`setup_offline.ps1` sẽ cài từ `offline_wheels\` và **bỏ qua** các
bước tải qua mạng (FFmpeg/Ollama/OmniVoice) — bạn cần chép sẵn các thư mục đó.

---

## 5. Chạy hệ thống

```powershell
.\run_native.ps1
```

- Mở nhiều cửa sổ console nền cho các dịch vụ. Cổng dùng: **8000** (orchestrator), **8001**
  (WhisperX), **9880** (TTS GPT-SoVITS), **3900** (OmniVoice), **11434** (Ollama), **5173**
  (frontend).
- Bỏ video `.mp4` vào `data\input\`, mở giao diện tại **http://localhost:5173**, lấy kết quả
  ở `data\output\`.
- Tắt hệ thống: đóng các cửa sổ console tương ứng.

---

## 6. Kiểm tra & xác minh môi trường

```powershell
# Báo cáo tình trạng hệ thống (OS, GPU, driver, VRAM, đĩa, cổng, tính toàn vẹn bundle)
.\Kiem-tra-he-thong.bat

# Unit test cho logic kiểm-tra phần cứng (chạy được ở mọi máy, không cần GPU/mạng)
powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_hardware_check.ps1
```

`preflight_check.ps1` và `setup_native.ps1` dùng **chung** ngưỡng trong `hardware_check.ps1`
(một nguồn sự thật), nên hai bên không bao giờ mâu thuẫn. Bộ test khoá các ngưỡng này lại.

---

## 7. (Nâng cao) Đóng gói bản cài để phát hành

Chỉ làm trên **máy đã cài đầy đủ** (có `venv` ML, model, Ollama). Sản phẩm: `Setup.exe + app.7z`.

### 7.1. Tiền đề bổ sung

| Tiền đề | Kiểm tra / cách đặt |
|---|---|
| **Python 3.10 base** (thành `python-runtime\`) | Mặc định tìm ở `%LOCALAPPDATA%\Programs\Python\Python310`, hoặc đặt `$env:PYTHON_RUNTIME_SRC`. |
| **Ollama runtime** (`ollama.exe` + `lib\`) | Mặc định `%LOCALAPPDATA%\Programs\Ollama`, hoặc đặt `$env:OLLAMA_SRC`. |
| **`venv` có torch + whisperx** | Do `setup_native.ps1` tạo. **Phải build bằng Python 3.10** (xem ⚠️ mục 2). |
| **Model đầy đủ** | `models\whisper`, `models\omnivoice`, `models\ollama` không rỗng. |
| **NSIS (`makensis.exe`)** | `build-electron.ps1` tự tải qua electron-builder; hoặc cài NSIS thủ công. |
| **Đĩa** | Ổ Stage ≥ 35 GB, ổ Out ≥ 20 GB (mặc định cả hai ở `D:`). |

### 7.2. Lệnh

```powershell
# Kiểm tra tiền đề (không phá gì, thoát sớm nếu thiếu)
.\build_deploy_bundle.ps1 -PreflightOnly

# Build đầy đủ: build-electron -> pack_full_bundle -> build_installer
.\build_deploy_bundle.ps1                       # mặc định Stage=D:\VD-Stage, Out=D:\VD-Installer
# .\build_deploy_bundle.ps1 -Stage "E:\Stage" -Out "E:\Out" -Mx 1
```

Kết quả: `Setup.exe` + `app.7z` trong thư mục `-Out`. **Ship CẢ HAI, để cùng thư mục.**

### 7.3. Các trình đóng gói khác

| Script | Dùng khi |
|---|---|
| `pack_full_bundle.ps1` | Stage bundle offline đầy đủ (~30 GB) cho `Setup.exe`. |
| `pack_transfer.ps1` | Gói **chuyển máy** (source + script cài, kèm `offline_wheels`/model nếu có) để máy đích tự cài online. |
| `pack_offline_bundle.ps1` | Chỉ tải sẵn wheel Python vào `offline_wheels\` (cho cài offline). |

---

## 8. Cấu trúc thư mục môi trường (sau khi cài)

```
PhuDe27.06/
├── venv/                 ← Python venv (torch cu118, whisperx, ...) — KHÔNG copy sang máy khác
├── python-runtime/       ← Base Python 3.10 (chỉ có trong bundle đóng gói)
├── ollama/               ← ollama.exe + lib\ (tự tải, hoặc bundle)
├── ffmpeg_extracted/     ← FFmpeg portable (tự tải)
├── models/
│   ├── whisper/          ← WhisperX large-v3-turbo
│   ├── omnivoice/        ← OmniVoice (có marker .download_complete)
│   ├── ollama/models/    ← LLM qwen2.5:14b (blobs/ + manifests/)
│   ├── demucs/ tts/ propainter/ latentsync/
├── data/{input,output,temp}/
├── orchestrator/ whisperx-service/ tts-service/ omnivoice-service/ frontend/
├── hardware_check.ps1    ← ngưỡng kiểm-tra phần cứng dùng chung (có test)
├── setup_native.ps1  setup_offline.ps1  run_native.ps1
├── preflight_check.ps1  Kiem-tra-he-thong.bat
└── build_deploy_bundle.ps1  pack_full_bundle.ps1  installer\installer.nsi
```

---

## 9. Khắc phục sự cố thường gặp

| Triệu chứng | Nguyên nhân / khắc phục |
|---|---|
| `[XX] VRAM: ... < 16 GB` khi chạy setup | GPU dưới 16 GB — không đủ chạy pipeline. Cần đổi GPU ≥ 16 GB. |
| `[XX] Python ... chưa có bản PyTorch CUDA 11.8` | Python ≥ 3.13 hoặc < 3.10. Cài Python 3.10.x, để lên đầu PATH, mở lại cửa sổ. |
| `[XX] Thiếu hardware_check.ps1` | File này phải nằm cạnh `setup_native.ps1`/`preflight_check.ps1`. `git pull` lại hoặc chép đủ. |
| Ollama tải model xong nhưng `models\ollama\models\blobs` rỗng | Đã sửa: setup dựng serve riêng cổng 11535 và kiểm tra blob. Nếu vẫn lỗi, tắt app Ollama đang chạy ở taskbar rồi chạy lại. |
| CUDA out of memory khi chạy | Kiểm tra `.env` có `VRAM_PROFILE=16gb` (setup tự ghi theo GPU). Giảm `TTS_CONCURRENCY`/`OMNIVOICE_REPLICAS` nếu vẫn OOM. |
| Cổng bị chiếm (8000/5173/11434…) | Đóng chương trình chiếm cổng (ví dụ Ollama chạy sẵn), hoặc đổi cổng trong `run_native.ps1`. |
| `makensis` không thấy khi build | Chạy `build-electron.ps1` một lần để electron-builder tải NSIS, hoặc cài NSIS thủ công. |

---

## 10. Tham chiếu nhanh

```powershell
# Dev từ đầu (máy đã cài Python 3.10 + Node + Git):
git clone -b feat/deployment-packaging https://github.com/levanhien54/PhuDe2706 PhuDe2706
cd PhuDe2706
.\setup_native.ps1        # cài + tải model tự động
.\run_native.ps1          # chạy -> http://localhost:5173

# Đóng gói bản cài (máy ML đầy đủ):
.\build_deploy_bundle.ps1 -PreflightOnly
.\build_deploy_bundle.ps1 # -> Setup.exe + app.7z
```
