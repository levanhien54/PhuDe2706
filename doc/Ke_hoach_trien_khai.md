# Tài liệu Thiết kế & Triển khai Hệ thống Video Dubbing & Dịch thuật Tự động (Bản Hợp nhất)

> **Ngày cập nhật:** 27/06/2026
> **Bản chất:** Tài liệu này gộp cấu trúc triển khai thực tế của dự án (v1.0) và các định hướng công nghệ SOTA 2025-2026 mới nhất (v2.0) thành một bản kế hoạch duy nhất, toàn diện và thống nhất.

---

## 1. Tổng quan & Mục tiêu Dự án
Hệ thống Video Dubbing & Dịch thuật Tự động 100% offline được tinh chỉnh chuyên biệt để tận dụng tối đa sức mạnh GPU phần khúc 16GB - 24GB.
- **Mục tiêu cốt lõi:** Xử lý xuyên suốt (end-to-end) từ khâu tách âm, nhận diện giọng nói (STT), dịch thuật ngữ cảnh (LLM), tổng hợp giọng nói (TTS), đồng bộ khẩu hình (Lip-sync), đến xuất video.
- **Tối ưu hóa VRAM:** Áp dụng phân bổ bộ nhớ động, nạp sẵn mô hình (Keep-alive) / Serving engine (vLLM) và Asynchronous Pipelining để các tiến trình chạy song song và luân phiên nhịp nhàng.
- **Chất lượng Đầu ra:** Dịch thuật sát ngữ cảnh, clone giọng tự nhiên mang cảm xúc, đồng bộ thời lượng và chuyển động môi (isochrony).

## 2. Cấu trúc Dự án
Dự án đã được phân tách áp dụng kiến trúc microservices:
```text
PhuDe27.06/
├── data/                      # Dữ liệu video đầu vào, đầu ra, file tạm
├── doc/                       # Tài liệu thiết kế (File này)
├── orchestrator/              # Module điều phối trung tâm
│   ├── main.py                # File điều phối pipeline chính (hỗ trợ định tuyến TTS_ENGINE)
│   ├── audio_sync.py          # Script đồng bộ âm thanh (time-stretch)
│   ├── video_process.py       # Tự động phát hiện và làm mờ chữ (PaddleOCR, OpenCV)
│   └── Dockerfile / requirements.txt
├── docker-compose.yml         # Cấu hình các container (OmniVoice, Ollama, WhisperX, Demucs, TTS)
└── ghichu.txt
```

## 3. Kiến trúc Hệ thống & Luồng Thực thi (Pipeline)

Hệ thống được vận hành qua lớp Điều phối Trung tâm (Orchestrator) với FastAPI/Celery hỗ trợ Async Pipelining. Dưới đây là sơ đồ pipeline đã cập nhật:

```text
   VIDEO GỐC
      │        ┌──────────────────────────────────────────────────────────────┐
      ├───────▶│ NHÁNH ÂM THANH                                                │
      │        │  M2 Tách âm: Demucs v4 (định hướng benchmark BS-Roformer)     │
      │        │  M3 STT+Align: WhisperX L-v3 + pyannote diarization           │
      │        │  M4 Dịch thuật: GemmaX2-28-9B (vLLM) hoặc Qwen2.5-14B         │
      │        │  M5 TTS Voice-Clone: OmniVoice-Studio hoặc GPT-SoVITS         │
      │        │  M6 Đồng bộ (Audio-sync): time-stretch (WSOLA/phase-vocoder)  │
      │        └──────────────────────────────────────────────────────────────┘
      │        ┌──────────────────────────────────────────────────────────────┐
      └───────▶│ NHÁNH HÌNH ẢNH                                                │
               │  M7 Phát hiện chữ: PaddleOCR (frame-skip 2 FPS)               │
               │  M8 Xóa chữ: OpenCV Gaussian Blur (định hướng ProPainter)     │
               └──────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
               ┌──────────────────────────────────────────────────────────────┐
               │  M9 LIP-SYNC (Mới): LatentSync / MuseTalk                     │
               │     Khớp chuyển động môi trên video với giọng tiếng Việt      │
               └───────────────────────────────┬──────────────────────────────┘
                                              ▼
               ┌──────────────────────────────────────────────────────────────┐
               │  M10 Mux & Render: FFmpeg + NVENC (vocals VI + background)    │
               └──────────────────────────────────────────────────────────────┘
                                              ▼
                                       VIDEO THÀNH PHẨM
```

## 4. Chi tiết Các Module & Công nghệ SOTA 2025-2026

### 4.1. Lớp Điều phối (Orchestrator) & Tối ưu VRAM
- **Serving LLM:** Định hướng chuyển từ "nạp/giải phóng thủ công của Ollama" sang dùng **vLLM + PagedAttention + Lượng tử hóa (AWQ/FP8)** để phục vụ dịch thuật nhanh gấp nhiều lần, giảm 50% nhu cầu VRAM.
- **Kỹ thuật tối ưu VRAM:** Tùy chọn nghiên cứu thêm **NEO** (CPU offloading attention) hoặc **Prism/kvcached** để chia sẻ bộ nhớ động giữa nhiều LLM/TTS trên cùng 1 card.

### 4.2. M2 - Tách Âm Thanh
- **Hiện tại:** Đang dùng **Demucs v4** (nhẹ, ~3GB VRAM, đã cấu trúc sẵn).
- **Nâng cấp:** Đưa **BS-Roformer / Mel-Band Roformer** vào benchmark để thử thách chất lượng tách vocal sạch hơn.

### 4.3. M3 - STT (Nhận diện giọng nói & Căn chỉnh thời gian)
- **Hiện tại:** **WhisperX (Large-v3)** + pyannote.
- **Nâng cấp:** Thử nghiệm mô hình nhẹ **Whisper Large-v3-Turbo** để tăng tốc độ nhận diện gấp 6 lần mà không suy giảm nhiều WER.

### 4.4. M4 - Dịch thuật ngữ cảnh (LLM)
- **Hiện tại:** **Qwen2.5-14B** (qua Ollama keep-alive).
- **Nâng cấp (Bắt buộc đo lường):** Chuyển sang dùng **GemmaX2-28-9B** làm mặc định (vì benchmark NAACL 2025 xác nhận vượt trội trong dịch đa ngôn ngữ, bao gồm Tiếng Việt). Giữ Qwen2.5-14B làm phương án đối chứng so sánh.

### 4.5. M5 - TTS & Voice Cloning
- **Đã tích hợp thực tế:** Hệ thống hiện hỗ trợ chuyển đổi linh hoạt bằng biến môi trường `TTS_ENGINE`.
  - `TTS_ENGINE=omnivoice`: Sử dụng container **OmniVoice-Studio** (`ghcr.io/debpalash/omnivoice-studio`) mới được tích hợp vào `docker-compose.yml`. Công cụ SOTA này hỗ trợ Zero-shot clone chỉ 3 giây, hơn 600 ngôn ngữ, và tự động offload xuống CPU nếu GPU đầy.
  - `TTS_ENGINE=gpt_sovits`: Engine dự phòng.
- **Hướng phát triển:** Dùng tính năng *Voice Design* của OmniVoice cho các video không có giọng chuẩn để tạo giọng lồng tiếng từ số không.

### 4.6. M7 & M8 - Xử lý Hình ảnh, OCR & Xóa Chữ
- **Đã tích hợp thực tế (`video_process.py`):** Sử dụng **PaddleOCR** quét 2 FPS để lấy tọa độ hộp chữ tĩnh/động. Kết hợp **OpenCV** để thực hiện Gaussian Blur trên mọi khung hình nhằm tối ưu tính toán.
- **Nâng cấp (ProPainter):** Thay thế blur bằng **ProPainter inpainting** (mạng neural khôi phục điểm ảnh) để xóa hoàn toàn chữ một cách liền mạch, nhưng cần đối chiếu tính hợp lệ License (chỉ cho phi thương mại) và xem xét yêu cầu VRAM cao nếu xử lý HD.

### 4.7. M9 - Lip-Sync (Đồng bộ Khẩu hình)
- **Nâng cấp trọng tâm của bản Hợp nhất:** Để đạt được "True lip-sync" (khớp môi thực tế), sẽ bổ sung module **LatentSync v1.5** (~8GB VRAM) vào đường ống ngay sau khi âm thanh được sinh ra.
- **Thay thế (cần tốc độ):** Dùng **MuseTalk** (single-pass nhanh hơn nhưng chất lượng thấp hơn chút đỉnh).
- Ở thiết lập 16GB, bắt buộc chạy Lip-sync **tuần tự** (tức là tải LLM/TTS ra khỏi VRAM trước).

## 5. Ngân sách VRAM & Luồng Thực thi

### Cấu hình 24GB (RTX 3090/4090) - Nạp Song song Tối đa
Với 24GB VRAM, hệ thống có thể nạp toàn bộ pipeline song song:
- Dịch (vLLM GemmaX2): ~7-9 GB
- TTS (OmniVoice/GPT-SoVITS): ~3-4 GB
- Lip-sync (LatentSync v1.5): ~8 GB
- Đệm/KV Cache: ~3-4 GB

### Cấu hình 16GB (RTX 4070 Ti/4080) - Chạy Luân phiên (Dynamic Allocation)
Cơ chế giải phóng linh hoạt sẽ tạo "khoảng trống" an toàn:
1. **Bước 1:** Demucs + PaddleOCR (~5GB VRAM) → Giải phóng ngay khi xong.
2. **Bước 2:** WhisperX + pyannote (~5GB VRAM) → Giải phóng.
3. **Bước 3:** GemmaX2 (Dịch) + OmniVoice (TTS) (~12GB VRAM).
4. **Bước 4:** *Bắt buộc giải phóng LLM*, sau đó nạp LatentSync v1.5 (~8GB VRAM) để chạy khớp khẩu hình.

## 6. Lộ trình Triển khai (Roadmap)

1. **Giai đoạn 0 (Thẩm định Cơ sở):** Chạy thử với bộ test Tiếng Việt. Đánh giá chất lượng dịch của GemmaX2 và độ tự nhiên giọng đọc của OmniVoice so với Qwen và GPT-SoVITS để đưa ra lựa chọn mặc định.
2. **Giai đoạn 1 (Lip-sync & Orchestrator):** Tích hợp Lip-sync (LatentSync) vào code `main.py` trước khâu FFmpeg. Triển khai cấu hình vLLM thay thế cho Ollama.
3. **Giai đoạn 2 (Hình ảnh & Đồng bộ nâng cao):** Nâng cấp `video_process.py` bằng ProPainter Inpainting thay vì chỉ Blur. Nghiên cứu Phase-vocoder để làm mịn việc kéo dãn giọng đọc.
4. **Giai đoạn 3 (SOTA Optimization):** Cấu hình NEO (offloading CPU) hoặc kvcached nếu thường xuyên gặp OOM khi vận hành nhiều video cùng lúc.

## 7. Rủi ro & Khuyến nghị Cần Lưu ý
- **VRAM của HD Video Inpainting:** ProPainter ngốn cực kỳ nhiều VRAM ở độ phân giải HD (1080p). Nếu dùng, phải chạy theo ô (tile) hoặc dùng Precision FP16.
- **Chất lượng thực tế của SOTA:** Mọi công nghệ mới (GemmaX2, OmniVoice, LatentSync) mặc dù có paper rất mạnh nhưng đều cần được tự thân thẩm định với **ngữ liệu Tiếng Việt thực tế** trước khi xóa bỏ hoàn toàn giải pháp cũ.
- **Metric tự động gây quyết định sai:** Luôn kết hợp đánh giá bằng cảm quan của người Việt (MOS/Human Evaluation) đối với bản dịch và chất giọng, không phụ thuộc 100% vào AI benchmark.
