# 02 — Sử dụng

Hướng dẫn sử dụng ứng dụng **Video Dubbing** (Studio Lồng Tiếng AI) sau khi
đã cài đặt và preflight báo `SẴN SÀNG` (xem `01-CAI-DAT.md`).

---

## 1. Mở app & màn hình khởi động

1. Nhấy đúp shortcut **"Video Dubbing"** trên Desktop hoặc Start Menu.
2. Một cửa sổ nhỏ (splash) hiện ra với thanh tiến trình và danh sách
   5 dòng trạng thái dịch vụ:

   ```
   GPU
   Dịch (Ollama)
   Nhận giọng
   Giọng đọc
   Điều phối
   ```

   Mỗi dòng có icon: ⏳ (đang kết nối) → ✅ (sẵn sàng) hoặc ❌ (lỗi).
   Ứng dụng khởi động các dịch vụ này **song song** nên thường mất khoảng
   **1–2 phút** cho lần chạy đầu (nạp model AI vào GPU — dịch vụ nhận diện
   giọng nói thường mất thời gian nhất).
3. Nếu có dòng ❌ kéo dài không chuyển sang ✅, sau vài chục giây một nút
   **"Mở thư mục log"** sẽ hiện ra — bấm để mở thư mục `data\` chứa file
   log phục vụ chẩn đoán (xem `03-XU-LY-SU-CO.md`).
4. Khi cả 5 dòng đều ✅, cửa sổ chính của ứng dụng tự động mở.

Sau khi vào giao diện chính, ở góc trên bên phải luôn có badge
**"Hệ thống: k/N sẵn sàng"** (xem mục 6 bên dưới) để theo dõi tình trạng
dịch vụ trong lúc dùng app.

---

## 2. Thêm video

Có hai cách:

- **Kéo-thả / chọn file**: ở khung **"Tải Video Lên"** trong sidebar bên
  trái, kéo file video vào khung có viền đứt nét, hoặc bấm nút **"Chọn
  file"** để mở hộp thoại chọn file. Định dạng hỗ trợ: **MP4, MKV, AVI**,
  dung lượng tối đa **500 MB** mỗi file.
- **Thư mục `data\input`**: chép trực tiếp file video (`.mp4`) vào thư mục
  `data\input` bên trong thư mục cài đặt ứng dụng.

Video mới sẽ xuất hiện trong danh sách **"Thư viện Video"** ở sidebar với
nhãn trạng thái **MỚI**.

---

## 3. Chọn cấu hình cho từng video

Chọn một video ở trạng thái **MỚI** trong thư viện để mở màn hình
**"Cấu hình lồng tiếng"**, gồm các tùy chọn:

| Tùy chọn | Mô tả |
|---|---|
| **Ngôn ngữ đích** | Tiếng Việt, Tiếng Anh (Mỹ/Anh), Tiếng Pháp, Tiếng Đức, Tiếng Nhật, Tiếng Hàn, Tiếng Bồ Đào Nha (Brazil), Tiếng Trung. |
| **Phong cách dịch** | Tiêu chuẩn (chính xác, tự nhiên) · Hài hước / Bắt trend (Gen Z) · Tài liệu / Trang trọng · Review phim / Châm biếm. |
| **Khớp môi (Lip Sync)** | Bật để dùng LatentSync khớp khẩu hình theo giọng mới — cần thêm **~8 GB VRAM** và **60–120 giây** xử lý thêm. |
| **Xóa chữ trong video (OCR)** | Tự động phát hiện và xử lý chữ/logo/watermark trên video. Khi bật, chọn thêm **chế độ xử lý chữ**: **"Làm mờ"** (Gaussian blur, nhanh) hoặc **"Xóa (AI Inpaint)"** (chậm hơn, sạch hơn). |
| **Chế độ giọng đọc** | **"Đa giọng (nhiều nhân vật)"** — tự nhận diện từng nhân vật và nhân bản giọng riêng cho mỗi người; hoặc **"Một giọng đọc"** — một giọng thuyết minh thống nhất cho cả video. Khi chọn "Một giọng đọc", có thêm mục **"Giọng đọc (clone theo quốc gia)"** để chọn giọng có sẵn theo quốc gia, hoặc để mặc định `⭐ Mặc định` để hệ thống tự nhân bản giọng người nói chính trong video. |

Sau khi chọn xong, bấm **"Bắt đầu lồng tiếng"**.

> Mẹo: có thể đặt cấu hình mặc định cho mọi video mới qua nút
> **"Cấu hình"** ở header (bánh răng), nơi cũng hiển thị **trạng thái dịch
> vụ** (Orchestrator, WhisperX STT, OmniVoice TTS) và cho phép chọn
> **thư mục lưu video** đầu ra khác thay vì mặc định `data\output`.

---

## 4. Theo dõi tiến trình xử lý (pipeline)

Sau khi bấm "Bắt đầu lồng tiếng", màn hình chuyển sang **"Tiến trình xử
lý"**, hiển thị các bước theo thứ tự:

1. **Tách Âm Thanh** — Demucs tách lời và nhạc nền.
2. **Nhận diện & Xóa Chữ** — PaddleOCR + OpenCV (chỉ chạy nếu đã bật OCR).
3. **Nhận diện Giọng nói** — WhisperX chuyển audio thành văn bản.
4. **Dịch thuật** — LLM (Qwen2.5 qua Ollama) dịch sang ngôn ngữ đích.
5. **Lồng Tiếng (TTS)** — OmniVoice tạo giọng mới, nhân bản giọng gốc.
6. **Khớp Khẩu Hình** — LatentSync (chỉ chạy nếu đã bật Lip Sync; nếu tắt,
   bước này hiển thị mờ với ghi chú "đã tắt").
7. **Kết xuất (Muxing)** — FFmpeg ghép audio mới vào video gốc.

Mỗi bước hiện trạng thái: đang chờ, đang chạy (xoay tròn), hoàn thành
(dấu tích, kèm thời gian đã mất), hoặc lỗi (thông báo lỗi màu đỏ). Badge
trạng thái tổng ở góc trên cũng hiển thị mã trạng thái hiện tại
(`PROCESSING`, `AWAITING_REVIEW`, `COMPLETED`, `FAILED`...).

Có thể bấm nút **hủy** (biểu tượng cấm ⊘) cạnh video trong sidebar để dừng
tiến trình đang chạy giữa chừng.

---

## 5. Review & sửa bản dịch (Hiệu đính Kịch bản)

Sau bước Dịch thuật, video chuyển sang trạng thái **CẦN DUYỆT**
(`AWAITING_REVIEW`). Đây là bước con người kiểm tra lại bản dịch trước khi
hệ thống tổng hợp giọng nói (TTS):

1. Trong sidebar, video sẽ có nhãn **CẦN DUYỆT** kèm nút bút chì (chỉnh
   sửa) — bấm để mở cửa sổ **"Hiệu đính Kịch bản (Human-in-the-loop)"**.
2. Mỗi đoạn thoại hiển thị: mốc thời gian, tên người nói (nếu nhận diện
   được), câu gốc, và ô nhập **bản dịch** — có thể sửa trực tiếp trong ô
   textarea. Thay đổi được **tự động lưu** sau khi ngừng gõ (~0.5 giây,
   có chỉ báo "Đang lưu..." rồi "Đã lưu").
3. Khi hài lòng với bản dịch, bấm **"Duyệt & Chạy tiếp (TTS)"** để tiếp
   tục pipeline (lồng tiếng, khớp môi nếu bật, và xuất video). Có thể bấm
   **"Để sau"** để đóng cửa sổ mà không chạy tiếp — video vẫn ở trạng thái
   CẦN DUYỆT, mở lại bất cứ lúc nào bằng nút bút chì.

---

## 6. Lấy kết quả

- Khi pipeline hoàn tất, video chuyển sang trạng thái **HOÀN THÀNH**.
  Chọn video đó để xem lại ngay trong trình phát video của ứng dụng.
- File video thành phẩm được lưu trong thư mục **`data\output`** (bên
  trong thư mục cài đặt), trừ khi đã đổi **"Thư mục lưu video"** khác
  trong màn **"Cấu hình"** (bánh răng ở header) — khi đó video xuất ra
  thư mục đã chọn.

---

## Badge "Hệ thống" ở header

Góc trên bên phải màn hình chính luôn có badge **"Hệ thống: k/N sẵn
sàng"** (ví dụ "Hệ thống: 4/4 sẵn sàng", xanh khi đủ). Bấm vào badge để
mở popover liệt kê chi tiết từng dịch vụ (Điều phối, Nhận giọng WhisperX,
Giọng đọc OmniVoice, Dịch Ollama/vLLM) — sẵn sàng hay chưa lên — cùng
thông tin GPU và VRAM đang sử dụng. Badge tự làm mới mỗi ~10 giây; nếu số
lượng dịch vụ sẵn sàng giảm giữa chừng khi đang dùng app, đó là dấu hiệu
một dịch vụ nền bị crash — xem `03-XU-LY-SU-CO.md`.

Ngoài ra, header còn có các nút:
- **"Làm mới"** — tải lại danh sách video trong thư viện.
- **"Tự động"** — cấu hình theo dõi một thư mục để tự động lồng tiếng mọi
  video mới thả vào (không cần thao tác thủ công từng video).
- **"Cấu hình"** — cấu hình mặc định (ngôn ngữ, phong cách, lip sync, OCR,
  thư mục lưu video) và xem nhanh trạng thái dịch vụ.
