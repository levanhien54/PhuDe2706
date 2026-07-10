# Đóng gói & Triển khai Tự động — Design Spec

Date: 2026-07-01
Status: Approved (proceed to implementation)

## Mục tiêu (Goal)

Đem app Video Dubbing sang **các máy Windows khác (đều có NVIDIA GPU)** một cách đơn giản
nhất, **mọi thứ tự động (kết nối service + kiểm tra sức khỏe)**, và tối ưu tốc độ ở các khâu
có thể. Kèm theo là **bộ tài liệu tiếng Việt** đóng chung bundle để người triển khai và người
dùng cuối tự làm được không cần hỏi.

Xây trên nền **mô hình đã duyệt** ở [2026-06-30-full-deployment-installer-design.md](2026-06-30-full-deployment-installer-design.md):
`Setup.exe` (NSIS) + `app.7z` (~20GB nén) → cài vào 1 thư mục tự chứa → double-click
`Video Dubbing.exe`. Spec này KHÔNG thay mô hình đó; nó **bổ sung lớp tự-kiểm-tra + tài liệu**
và tích hợp vào pipeline build sẵn có.

## Bối cảnh hiện có (đã build)

- `build-electron.ps1` → `Video Dubbing.exe` (Electron portable, nạp `frontend/dist` từ đĩa).
- `pack_full_bundle.ps1` → stage thư mục tự chứa (exe + venv cu118 + python-runtime +
  models + ollama + ffmpeg + source + `.env`).
- `build_installer.ps1` → nén stage thành `app.7z` (7z mx=1) + biên dịch `Setup.exe` (NSIS).
- `installer/installer.nsi` → installer: dir picker, shortcut, uninstaller, repair `pyvenv.cfg`.
- `electron/main.js` → tự spawn 4 service Python (orchestrator/whisperx/tts/omnivoice) +
  ollama, repair `pyvenv.cfg`, `waitForPort(8000)` rồi mở cửa sổ chính. Đã fix cho máy sạch.

## Yêu cầu (từ user)

1. Mô hình: **Setup.exe + app.7z offline** (giữ nguyên).
2. Máy đích: **đều có NVIDIA GPU + Windows 10/11** (giống máy nguồn; venv cu118 dùng chung).
3. Tự động: **cả preflight (trước khi dùng) LẪN dashboard trong app** (auto-connect + health-check).
4. Tài liệu: **Cài đặt máy đích + Sử dụng + Xử lý sự cố** (tiếng Việt). *Không* cần HD đóng gói.
5. Tốc độ nhanh ở các khâu tối ưu được (nén nhanh, khởi động song song, dashboard minh bạch).

## Ngoài phạm vi (Non-goals)

- Bản CPU-only (không GPU) — venv riêng, việc lớn.
- Auto-update phiên bản.
- Sửa kiến trúc sang server-client.
- Tài liệu hướng dẫn đóng gói cho người build (user không yêu cầu).

---

## Thành phần 1 — Preflight checker

**Mục đích:** một lệnh double-click trên máy đích xác nhận môi trường đạt yêu cầu TRƯỚC khi
chạy app, báo cáo rõ ràng bằng tiếng Việt.

**Interface:**
- `preflight_check.ps1` — script chính (PowerShell). Tham số tùy chọn `-Root <path>` (mặc định
  thư mục chứa script). Trả exit code 0 (tất cả PASS) / 1 (có FAIL).
- `Kiểm tra hệ thống.bat` — launcher: gọi `powershell -ExecutionPolicy Bypass -File preflight_check.ps1`,
  `pause` để người dùng đọc kết quả. Đây là thứ người dùng double-click.

**Các mục kiểm tra** (mỗi mục in `[ĐẠT]` / `[LỖI]` / `[CẢNH BÁO]` + câu giải thích + cách sửa):
1. **OS**: Windows 10/11, kiến trúc x64.
2. **GPU + driver**: `nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader`.
   - LỖI nếu không có `nvidia-smi` hoặc không có GPU.
   - CẢNH BÁO nếu `driver_version` < 452.39 (ngưỡng an toàn tối thiểu cho CUDA 11.8 forward-compat).
   - LỖI nếu VRAM < 16000 MiB; ghi rõ profile phù hợp (16GB/24GB).
3. **Đĩa trống**: ổ chứa thư mục cài phải còn ≥ 35 GB.
4. **Port trống**: 8000, 8001, 9880, 3900, 11434, 5173 — dùng `Get-NetTCPConnection -State Listen`;
   CẢNH BÁO (không LỖI) nếu cổng đang bị chiếm (nêu process đang giữ nếu lấy được).
5. **Toàn vẹn bundle** (chỉ chạy khi `-Root` là thư mục cài): tồn tại `venv\Scripts\python.exe`,
   `python-runtime\python.exe`, `frontend\dist\index.html`, `.env`, `ollama\ollama.exe`,
   `ffmpeg_extracted\*\bin\ffprobe.exe`, `models\whisper`, `models\omnivoice`,
   `models\ollama\models\blobs` (store LLM), `Video Dubbing.exe`.
6. **pyvenv.cfg**: kiểm `venv\pyvenv.cfg` có dòng `home =` và `python-runtime\python.exe` tồn tại
   (để `repairVenvConfig()` của main.js hoạt động).

**Đầu ra:** in ra console có màu + ghi `preflight_report.txt` cạnh script (timestamp + kết quả
từng mục). Tổng kết cuối: "SẴN SÀNG" (0 lỗi) hoặc "CHƯA ĐẠT: <n> lỗi — xem chi tiết ở trên".

**Tích hợp:** `installer.nsi` tự chạy `Kiểm tra hệ thống.bat` (hoặc trực tiếp script) ở cuối bước
cài và hiện kết quả; KHÔNG chặn hoàn tất cài (hướng A — chỉ báo). Cũng có shortcut Start-Menu.

## Thành phần 2 — Dashboard tự kết nối/kiểm tra trong app

### 2a. Splash checklist (electron)
- `electron/main.js`: sau khi spawn service, thay vì chỉ `waitForPort(8000)`, thực hiện thêm:
  - Chạy nhanh `nvidia-smi` (một lần) → gửi trạng thái GPU.
  - Poll health từng service song song với backoff: orchestrator `GET :8000/api/health`
    (endpoint mới, xem 2c), và trực tiếp `:8001/health`, `:9880/health` (nếu có), `:3900/health`,
    ollama `:11434/api/tags`. Với service chưa có `/health`, coi "listening port" là tạm ổn.
  - Gửi cập nhật sang `splash.html` qua `ipcMain`→`webContents.send('service-status', {...})`.
- `electron/splash.html` + `electron/preload.js`: hiển thị danh sách 6 dòng
  **GPU · Ollama (LLM) · WhisperX · TTS · OmniVoice · Orchestrator**, mỗi dòng có icon trạng thái
  *đang kết nối (spinner) → sẵn sàng (✓) / lỗi (✗)*. Khi có service lỗi sau N lần retry: hiện
  câu gợi ý + nút "Mở thư mục log" (`data/*.log`). Cửa sổ chính vẫn chỉ mở khi orchestrator sẵn
  sàng (như hiện tại), nhưng người dùng THẤY tiến trình thay vì màn chờ câm.
- `preload.js` phải `contextBridge.exposeInMainWorld` một API nhỏ (`onServiceStatus`, `openLogs`)
  — giữ `contextIsolation:true`.

### 2b. Health badge trong UI (frontend)
- Thêm chỉ báo gọn ở header: **"Hệ thống: k/6 sẵn sàng"** (xanh nếu đủ). Bấm mở popover liệt kê
  từng service up/down + VRAM đang dùng (từ `/api/health`). Poll mỗi ~10s, dừng khi tab ẩn.
- Component mới `frontend/src/components/SystemStatus.jsx` + style; gắn vào `App.jsx` header.

### 2c. Endpoint sức khỏe tổng hợp (orchestrator)
- `GET /api/health` trong `orchestrator/api.py`: ping song song (httpx, timeout ngắn) các service
  con (`WHISPERX_API/health`, `TTS_API/health` hoặc `/`, omnivoice `/health`, ollama `/api/tags`)
  + đọc VRAM qua `nvidia-smi` (hoặc torch nếu rẻ). Trả **luôn 200** với JSON:
  ```json
  {"services": {"orchestrator":"up","whisperx":"up|down","tts":..., "omnivoice":..., "ollama":...},
   "ready": 5, "total": 5, "gpu": {"name":..., "vram_used_mb":..., "vram_total_mb":...}}
  ```
  Không chặn/không ném lỗi khi service con down (trả `"down"`). Có cache ngắn (~2s) để poll rẻ.

## Thành phần 3 — Bộ tài liệu (tiếng Việt)

Thư mục `HƯỚNG-DẪN/` ở repo root (được `pack_full_bundle.ps1` stage vào bundle → có trên máy đích):
- `QUICKSTART.txt` — 1 trang in được, 5 bước: (1) chép `Setup.exe`+`app.7z` vào cùng thư mục,
  (2) chạy `Setup.exe` chọn nơi cài, (3) double-click **"Kiểm tra hệ thống"**, (4) double-click
  **"Video Dubbing"**, (5) đợi splash báo đủ service → dùng.
- `01-CÀI-ĐẶT.md` — yêu cầu phần cứng (bảng), điều kiện driver, từng bước cài chi tiết, cách đọc
  preflight report, phải làm gì khi từng mục FAIL.
- `02-SỬ-DỤNG.md` — bỏ/kéo-thả video, chọn cấu hình (lồng tiếng, OCR/xóa chữ, lip-sync), theo dõi
  pipeline, review & sửa bản dịch, lấy kết quả ở `data/output`, chọn thư mục xuất.
- `03-XỬ-LÝ-SỰ-CỐ.md` — bảng lỗi→nguyên nhân→cách sửa: thiếu/cũ driver, OOM VRAM (đổi
  `VRAM_PROFILE`), port bận, model thiếu, service không lên, Ollama không thấy model, vị trí log.

Tài liệu dùng ngôn ngữ đơn giản, có ảnh chụp/sơ đồ ASCII khi cần, khớp UI thực tế.

## Thành phần 4 — Tích hợp build & Tốc độ

- `pack_full_bundle.ps1`: stage thêm `preflight_check.ps1`, `Kiểm tra hệ thống.bat`, thư mục
  `HƯỚNG-DẪN/` vào `$Stage`.
- `installer/installer.nsi`: đóng kèm docs + `.bat`; thêm shortcut Start-Menu "Kiểm tra hệ thống";
  chạy preflight cuối bước cài và hiện report.
- **Tốc độ:**
  - Giữ nén **7z mx=1** (giải nén nhanh; payload phần lớn là weight/dll khó nén).
  - Khởi động service **song song** (main.js đã spawn cùng lúc) — không tuần tự hóa.
  - Dashboard cho tiến trình rõ → giảm cảm giác chờ; tài liệu ghi **thời gian dự kiến** (copy 20GB
    theo tốc độ ổ đĩa; cài/giải nén vài phút; khởi động lần đầu ~1–2 phút nạp model, whisperx lâu
    nhất). Cân nhắc để `WHISPER_PRELOAD` mặc định tắt (nạp lười) để cửa sổ mở sớm.

## Thành phần 5 — Kiểm thử & Bàn giao

- **Preflight**: tách logic kiểm tra thành các hàm thuần để test được; test với input giả
  (chuỗi `nvidia-smi` giả, thiếu file, port bận). Dry-run `preflight_check.ps1` trên máy nguồn.
- **/api/health**: unit test (mock httpx như `test_llm_client`) — trả đúng cấu trúc + luôn 200 kể
  cả khi service con down.
- **Frontend**: `SystemStatus.jsx` lint + build; kiểm render với dữ liệu health giả.
- **Docs**: tự rà + user review.
- **Build + verify (bước cuối, do user chạy):** `build-electron.ps1` → `pack_full_bundle.ps1` →
  `build_installer.ps1` → cài `app.7z` sang **thư mục/máy khác**, chạy preflight, mở app, xác nhận
  đủ service + repair pyvenv + Ollama + FFmpeg. **Không thể verify trên máy sạch từ phiên này**;
  spec/plan chuẩn bị sẵn, tôi có thể chạy `pack_full_bundle` nếu user muốn (cần ~60GB đĩa tạm).

## File-by-file (dự kiến)

| File | Thay đổi |
|---|---|
| `preflight_check.ps1` (mới) | Toàn bộ logic preflight. |
| `Kiểm tra hệ thống.bat` (mới) | Launcher double-click. |
| `electron/main.js` | Thu thập trạng thái GPU + health từng service, gửi IPC cho splash. |
| `electron/splash.html` (sửa) | Checklist 6 service + retry + nút mở log. |
| `electron/preload.js` | Expose `onServiceStatus`, `openLogs`. |
| `orchestrator/api.py` | Thêm `GET /api/health` tổng hợp. |
| `frontend/src/components/SystemStatus.jsx` (mới) + `App.jsx` | Badge + popover trạng thái. |
| `pack_full_bundle.ps1` | Stage preflight + docs. |
| `installer/installer.nsi` | Đóng kèm docs/.bat, shortcut, auto-run preflight. |
| `HƯỚNG-DẪN/{QUICKSTART.txt,01-CÀI-ĐẶT.md,02-SỬ-DỤNG.md,03-XỬ-LÝ-SỰ-CỐ.md}` (mới) | Bộ tài liệu. |
| `tests/test_api_health.py` (mới) | Test `/api/health`. |

## Rủi ro / Điểm cần lưu ý

- Service con hiện có thể chưa có endpoint `/health` đồng nhất → `/api/health` phải chịu lỗi tốt
  (coi không phản hồi = "down"), và splash fallback theo "port listening".
- `nvidia-smi` có thể không nằm trên PATH ở vài máy → thử cả `C:\Windows\System32\nvidia-smi.exe`.
- Tên file tiếng Việt có dấu (`Kiểm tra hệ thống.bat`, `HƯỚNG-DẪN/`) phải chắc chắn encode UTF-8
  và NSIS đóng gói đúng; nếu rủi ro, thêm bản ASCII `Kiem-tra-he-thong.bat` song song.
- Không thể verify clean-machine từ phiên này (đã nêu ở Thành phần 5).
