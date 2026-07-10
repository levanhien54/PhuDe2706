# Kế hoạch khắc phục sau audit toàn dự án — 08/07/2026

Nhánh: `feat/deployment-packaging`. Baseline test: **105 pass / 0 fail**.

## Phương pháp
- Fan-out **7 agent audit song song** (read-only) theo 7 vùng độc lập; mỗi finding phải kèm file:line + kịch bản lỗi cụ thể.
- **Xác minh đối kháng** 13 finding HIGH/MEDIUM trọng yếu bằng workflow 20 verifier (HIGH: 2 lens code+reachability/finding). Mỗi verifier cố **bác bỏ** finding bằng code hiện tại.
- Chỉ finding sống sót verify mới vào kế hoạch với severity đã hiệu chỉnh.

## Kết quả verify — các thay đổi quan trọng so với báo cáo thô
Gộp thô 66 finding (7 HIGH). Sau verify chỉ **1 HIGH thật**; 6 HIGH còn lại bị hạ cấp:

| Finding thô | Verdict verify | Severity cuối | Lý do hiệu chỉnh |
|---|---|---|---|
| Blur-mode fallback ship phụ đề + báo thành công | CONFIRMED (2/2 lens) | **HIGH** | Đường mặc định; lỗi âm thầm ship output sai |
| whisperx CUDA DLL hardcode `ezycloudx-admin` | code CONFIRMED / reach UNVERIFIABLE | **HIGH-deploy** | Path dev chắc chắn sai; blast-radius nhẹ hơn (có CPU fallback + venv có thể tự có cublas64_12) nhưng PHẢI bỏ trên nhánh deploy |
| SĐT Hàn bị phá (`_ranges_to_words` trước `normalize_korean`) | CONFIRMED (chạy code) | MEDIUM | Sai rõ nhưng không crash, input hẹp (SĐT/mã gạch nối) |
| Frontend poller hủy nhầm job | CONFIRMED (2/2) | MEDIUM | Có thật; cửa sổ timing hẹp, tự sửa khi chọn lại |
| tts-service thiếu lock model dùng chung | CONFIRMED (2/2) | MEDIUM | Có thật |
| **run_native.ps1 hardcode Ollama** | **REJECTED (reach)** | LOW | run_native.ps1 KHÔNG phải launcher máy đích — bundle NSIS dùng `electron/main.js` xử lý Ollama đúng (add bundled dir vào PATH + spawn bundled exe). Chỉ dọn cho sạch |
| **ReviewModal trắng màn hình** | **REJECTED (reach)** | LOW | Backend luôn trả `{"segments":[list]}`; không reachable. Chỉ thêm `\|\| []` + ErrorBoundary phòng thủ |
| **Empty-transcript → thành công giả** | **REJECTED (harm)** | LOW | phase-2 `synthesize` có guard empty-audio → mark job FAILED. Không ship output sai; chỉ nên fail-fast sớm với lý do rõ |
| **stretch_audio không đạt target** | **REJECTED (reach)** | NIT | Caller `synthesize.py` trim theo slot kế + zero-pad → không overlap |
| omnivoice /health block khi cold-load | CONFIRMED | LOW | Hạ từ MEDIUM |

→ **4 finding bị bác/hạ mạnh, tránh over-engineer.**

---

## Phân phối severity cuối
- **HIGH: 1** (+ 1 HIGH-deploy phải xử lý trên nhánh này)
- **MEDIUM: ~22** (gồm 4 GPU-gated cần verify máy thật)
- **LOW: ~26**, **NIT: ~12**

---

## KẾ HOẠCH KHẮC PHỤC THEO PHASE

### PHASE 0 — Lỗi correctness ship output sai âm thầm (ưu tiên cao nhất, dev-feasible, rủi ro thấp)
| # | Lỗi | File | Cách sửa |
|---|---|---|---|
| 0.1 | **Blur-mode fallback blur rỗng nhưng báo success** | `orchestrator/video_process.py:1038-1075` | Nhánh except của precise-blur (blur mode): re-raise (để `video_ocr` báo FAIL) HOẶC precompute `ocr_lookup` trước khi vào fallback. Không được trả success khi không blur gì |
| 0.2 | **SĐT Hàn bị phá** | `orchestrator/text_normalize.py:552` (+321) | Chạy phone/digit-spelling TRƯỚC `_ranges_to_words` cho `ko` (soi lại `ja`/`de` cùng lỗi cấu trúc) — mirror đúng path `vi` (`_vi_pre` chạy trước) |
| 0.3 | **Crash IndexError số ≥21 chữ số (KO/JA)** → drop segment | `text_normalize.py:278` (`_ko_read_sino`), `:478` (`_ja_read`) | Khi `len(groups) > len(_KO_BIG_UNITS/_JA_BIG)` → đọc digit-by-digit (như VN đã làm ở `read_number`) |
| 0.4 | Số cuối câu tiếng Đức → số thứ tự + mất dấu chấm | `text_normalize.py:410-411` | Chỉ coi `N.` là ordinal khi theo sau là space+chữ thường (vd `am 3. mai`); giữ dấu chấm ở ranh giới câu |
| 0.5 | Ký hiệu tiền tệ bất đối xứng ($/€/£) còn thô trong text | `text_normalize.py` de:408, en:233-234, ko:312 | Thêm rule mirror thiếu mỗi ngôn ngữ (dùng VI 156-159 làm chuẩn) |
| 0.6 | **Watch-folder scan đồng thời → job trùng + hỏng `.part`** | `orchestrator/api.py:132-174` | Bọc `scan_watch_folder_once` bằng `asyncio.Lock`; đặt tên `.part` duy nhất theo job_id/uuid |
| 0.7 | **tts-service thiếu lock model dùng chung** | `tts-service/app.py:156,194` | Thêm `threading.Lock` quanh lazy-init VÀ vòng `tts.run()` (như 2 service anh em) |
| 0.8 | tts-service `/unload` không giải phóng model | `tts-service/app.py:112` | Set `_tts_instance=None; _tts_config=None` trước `empty_cache()` |
| 0.9 | **GPU subprocess không timeout → treo worker vô hạn** | `stages/latentsync_client.py:50`, `musetalk_client.py:53`, `propainter_client.py:51`, `clients/bs_roformer_client.py:46`, `demucs_client.py:42` | Bọc `communicate()` trong `asyncio.wait_for(timeout)`; kill+wait khi `TimeoutError` (mirror guard CancelledError sẵn có) |

### PHASE 1 — Robustness người dùng thấy được (dev-feasible)
| # | Lỗi | File | Cách sửa |
|---|---|---|---|
| 1.1 | Poller hủy nhầm job | `frontend/src/App.jsx:75-110` | Lưu id `setTimeout` để `clearTimeout` khi cleanup; `fetchStatus` early-return nếu `stopped`/`selectedVideo` đã đổi trước khi `setStatusData` |
| 1.2 | Nút "Bắt đầu" double-click → job trùng | `App.jsx:133,328` | State `isStarting`, disable nút + early-return khi đang gửi |
| 1.3 | ReviewModal autosave fail âm thầm + resume không flush | `ReviewModal.jsx:40-65` | Render trạng thái `error`; `handleResume` flush/await debounce trước khi POST |
| 1.4 | Electron thiếu single-instance lock | `electron/main.js:459` | `app.requestSingleInstanceLock()`; instance 2 → focus cửa sổ cũ rồi quit |
| 1.5 | Poller core không timeout fetch → treo poll | `App.jsx:41-95` | Thêm `AbortSignal.timeout(...)` như `ConfigModal`/`SystemStatus` |
| 1.6 | whisperx upload đọc full vào RAM | `whisperx-service/app.py:224` | Stream theo chunk vào temp file |
| 1.7 | tts-service fallback edge-tts = ONLINE trong sản phẩm offline | `tts-service/app.py:29,125` | Sửa default `GPT_SOVITS_DIR` cho Windows; fallback offline thật hoặc báo lỗi rõ (không im lặng gọi mạng) |
| 1.8 | Re-encode constant-fps → lệch A/V trên nguồn VFR | `video_process.py:800,1086` | `-fps_mode passthrough`/giữ PTS cho input non-CFR thay vì `-r` cố định |
| 1.9 | Empty-transcript nên fail-fast có lý do | `pipeline.py:91`, `api.py:354` | Coi 0 segment là phase-1 FAIL với reason "no speech detected" (tránh phí 1 vòng phase-2) |
| 1.10 | Engine router case-sensitive + fallback im lặng | `tts_client.py:45`, `llm_client.py:80`, `audio_separate.py:16`, `lip_sync.py:32` | `.lower()` + raise/log khi giá trị lạ |
| 1.11 | Retry bỏ sót `RemoteProtocolError`/`ReadError` | `clients/base.py:40` | Thêm vào tuple retry (cân nhắc `httpx.TransportError`) |

### PHASE 2 — Hardening triển khai (đúng mục đích nhánh này)
| # | Lỗi | File | Cách sửa |
|---|---|---|---|
| 2.1 | **Hardcode path CUDA DLL `ezycloudx-admin`** | `whisperx-service/app.py:19-21` | Tính path bundle-relative `ollama/lib/ollama/cuda_v12/*`; bỏ path dev; log rõ nếu không tìm thấy cublas64_12; kiểm venv có `nvidia-cublas-cu12` |
| 2.2 | Offline pack gộp `vllm` với deps bắt buộc, không check exit | `pack_offline_bundle.ps1:39`, `setup_offline.ps1:54` | Tách `vllm` best-effort (như `setup_native.ps1`); thêm `$LASTEXITCODE` check cho deps bắt buộc |
| 2.3 | NSIS `RMDir /r $INSTDIR` xoá data người dùng | `installer/installer.nsi:108` | Chỉ xoá payload đã biết; giữ/hỏi `data\output`; chặn uninstall thư mục user chọn |
| 2.4 | `pack_transfer.ps1` robocopy không guard exit | `pack_transfer.ps1` (10 chỗ) | Route qua helper coi exit `>=8` là fail (như `pack_full_bundle.ps1`) |
| 2.5 | run_native.ps1 fallback path Ollama hardcode | `run_native.ps1:133-139` | Thêm `$ProjectRoot\ollama\ollama.exe` làm candidate đầu; bỏ path `ezycloudx-admin` |
| 2.6 | Parity script bash (non-target, nếu còn dùng Linux) | `setup_native.sh:88`, `pack_offline_bundle.sh`, `run_native.sh:20-30` | Port `.part`+atomic-replace; mirror danh sách wheel; default TTS `omnivoice`; parse `.env` an toàn |

### PHASE 3 — GPU-gated (KHÔNG sửa mù — verify trên máy GPU thật)
| # | Lỗi | File | Ghi chú |
|---|---|---|---|
| 3.1 | MuseTalk output-glob có thể promote video gốc thành kết quả | `stages/musetalk_client.py:67-74` | Thêm assert file chọn ≠ `video_path`; dùng subdir output riêng rỗng; **chỉ chốt được khi chạy MuseTalk thật** |
| 3.2 | ProPainter lấy `os.listdir()[0]` sai file | `stages/propainter_client.py:57-66` | Match tên `inpaint_out.*`, search đệ quy; **verify tên/layout khi chạy thật** |
| — | Checklist verify GPU cũ (vLLM AWQ, whisper-turbo WER, BS-Roformer, ProPainter HD flags) | (memory) | Vẫn treo, cần máy GPU |

### PHASE 4 — LOW/NIT (gom batch, rủi ro thấp)
Frontend: `res.ok` cho fetchVideos (F7); guard `v.status` (F8); Uploader disable drop khi upload + size check (F9); CSP/`webSecurity` (F10); ConfigModal dùng `API_BASE` (F11); Toast timer (F12); lỗi upload `detail` (F13); ReviewModal `|| []`+ErrorBoundary (F2).
Core: scan offload thread (A3); upload cleanup `except Exception` (A4); QUEUED recovery (A5); worker cancel re-raise (A6); logger dùng `data_dir` (A7); `_cancel_requested` cleanup (A8).
Video: `_resolve_ffmpeg` trong video_process (V4); precompute frame-0 collapse khi count=0 (V5); copy-through khi count unknown (V6); voice_ref thiếu `file` (V7); scale zero-width (V8).
Clients/TTS-norm: batch translate validate id set (C6); retry bỏ sleep cuối + jitter (C8); test cancel musetalk/bsroformer + dọn `.yaml` (C9); dấu âm (T5); VN acronym 5+ letter + `×÷` khỏi `_L` (T6).
Services: whisperx temp cleanup Windows (S6); tts-service ffmpeg PATH + tmp leak (S7); omnivoice cờ `voice_cloned:false` (S8); tts-service tên tmp không phụ thuộc `.wav` (S9); whisperx /unload lock (S10); validate độ dài text (S11); omnivoice /health non-block (S3).
Deploy: `2>&1`→`2>$null` (D10); đổi tên `$args` (D11).

---

## Thứ tự thực thi đề xuất
1. **Phase 0** trước (correctness, có test hồi quy cho mỗi fix) → chạy `venv/Scripts/python.exe -m pytest tests/ -q`.
2. **Phase 1** (robustness dev-feasible).
3. **Phase 2** (deploy hardening — chốt trước khi build bundle máy GPU).
4. **Phase 4** gom cuối.
5. **Phase 3** chỉ khi có máy GPU thật.

Mỗi fix: 1 commit theo severity, kèm test hồi quy khi khả thi (theo tiền lệ 2 đợt hardening trước).
