# 03 — Xử lý sự cố

Bảng tra cứu nhanh **Triệu chứng → Nguyên nhân → Cách sửa** cho các lỗi
thường gặp khi cài đặt và sử dụng Video Dubbing.

---

## Vị trí log để chẩn đoán

| Log | Vị trí | Ghi chú |
|---|---|---|
| Log tổng của Orchestrator (bộ điều phối pipeline) | `data\orchestrator.log` | File xoay vòng (tối đa 5 MB × 3 bản), chứa log chi tiết từng bước xử lý video (M2→M10), lỗi dịch, lỗi TTS... |
| Log các dịch vụ Python khác (WhisperX, TTS, OmniVoice, Ollama) | Cửa sổ console ẩn của từng tiến trình | Các dịch vụ này in log ra output của tiến trình con do Electron quản lý; khi ứng dụng đang chạy, mở **Task Manager** hoặc dùng nút **"Mở thư mục log"** trên màn hình khởi động (splash) để mở thư mục `data\` — nếu cần xem log trực tiếp của một dịch vụ, có thể tạm thời chạy `run_native` tương ứng từ dòng lệnh để thấy output console đầy đủ. |
| Báo cáo preflight | `preflight_report.txt` (cạnh `Kiem-tra-he-thong.bat`) | Kết quả lần kiểm tra hệ thống gần nhất — xem lại bất cứ lúc nào. |

Cách mở nhanh thư mục `data\`: trên màn hình khởi động (splash), nếu một
dịch vụ báo lỗi kéo dài sẽ xuất hiện nút **"Mở thư mục log"** — bấm vào đó.

---

## Bảng triệu chứng → nguyên nhân → cách sửa

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| Preflight báo **`[FAIL] GPU NVIDIA`** hoặc không tìm thấy `nvidia-smi` | Máy không có GPU NVIDIA, hoặc chưa cài driver. | Cắm/kiểm tra GPU NVIDIA vật lý; cài driver mới từ [nvidia.com/drivers](https://www.nvidia.com/drivers); khởi động lại máy. |
| Preflight báo **`[WARN] Driver GPU`** (driver cũ) | Driver hiện tại thấp hơn phiên bản 452.39, có thể không tương thích CUDA 11.8. | Cập nhật driver NVIDIA lên bản mới nhất, khởi động lại máy, chạy lại `Kiem-tra-he-thong.bat`. |
| Ứng dụng dừng đột ngột hoặc lỗi hiện chữ **"CUDA out of memory"** trong `data\orchestrator.log` | GPU không đủ VRAM trống cho cấu hình hiện tại (ví dụ đang chạy nhiều tác vụ khác trên GPU, hoặc GPU chỉ có đúng 16 GB và đang dùng profile 24gb). | Mở file `.env` trong thư mục cài đặt, đặt `VRAM_PROFILE=16gb`, lưu file rồi khởi động lại ứng dụng. Đóng các phần mềm khác đang chiếm VRAM (trình duyệt nhiều tab nặng, phần mềm đồ họa/game). Nếu vẫn lỗi, tắt bớt tính năng nặng (Lip Sync, OCR chế độ AI Inpaint) cho video đó. |
| Preflight báo **`[WARN] Cổng <số>`: đang bị chiếm** hoặc ứng dụng không khởi động được dịch vụ | Một chương trình khác (hoặc phiên chạy cũ của chính ứng dụng) đang chiếm cổng 8000/8001/9880/3900/11434/5173. | Mở PowerShell, chạy `Get-NetTCPConnection -LocalPort <số cổng> -State Listen` để xem tiến trình đang giữ cổng (cột `OwningProcess`, tra tên bằng `Get-Process -Id <PID>`); đóng tiến trình đó (ví dụ Ollama đang chạy sẵn ngoài ứng dụng), hoặc khởi động lại máy nếu không rõ tiến trình nào. Sau đó chạy lại `Kiem-tra-he-thong.bat` để xác nhận cổng đã trống. |
| Preflight báo **`[FAIL] Bundle: <tên file/model>` — THIẾU** | Bản cài đặt bị thiếu file hoặc model (do `app.7z` bị cắt ngắn/hỏng khi tải hoặc copy). | Xóa thư mục đã cài, tải/copy lại `Setup.exe` + `app.7z` đầy đủ (kiểm tra dung lượng file khớp với bản gốc), cài lại từ đầu. |
| Một dòng trên màn hình khởi động (splash) hiện **❌** không chuyển sang ✅ | Dịch vụ tương ứng (GPU / Ollama / WhisperX / OmniVoice / Orchestrator) không khởi động được hoặc bị treo. | Bấm nút **"Mở thư mục log"** xuất hiện trên splash sau vài chục giây, mở `data\orchestrator.log` để xem lỗi cụ thể. Đóng ứng dụng, khởi động lại. Nếu dịch vụ báo lỗi là GPU, xem mục driver/VRAM ở trên. Nếu là Ollama, xem mục kế tiếp. |
| Badge **"Hệ thống"** trong app hiển thị số dịch vụ sẵn sàng bị giảm (ví dụ "3/4") khi đang dùng | Một dịch vụ nền bị crash giữa chừng khi đang xử lý (thường do hết VRAM hoặc lỗi model). | Mở `data\orchestrator.log` tìm dòng lỗi gần nhất ứng với thời điểm badge đổi. Thử khởi động lại ứng dụng (đóng hẳn "Video Dubbing" rồi mở lại) để các dịch vụ được spawn lại từ đầu. |
| Bước **Dịch thuật** báo lỗi, hoặc Ollama không tìm thấy model (log có dòng kiểu "model not found") | Biến môi trường `OLLAMA_MODELS` trỏ sai thư mục, hoặc model LLM chưa được tải/giải nén đúng chỗ trong bundle. | Kiểm tra thư mục `models\ollama\models` trong thư mục cài đặt có tồn tại và có dữ liệu (thư mục `blobs`) không — nếu thiếu, đây là lỗi bundle (xem mục "Bundle thiếu" ở trên, cài lại). Nếu thư mục vẫn có dữ liệu nhưng vẫn lỗi, thử khởi động lại ứng dụng để Electron gán lại `OLLAMA_MODELS` đúng theo đường dẫn cài đặt thực tế. |
| Xóa chữ/watermark (OCR) chạy rất chậm | Chế độ **"Xóa (AI Inpaint)"** nặng hơn nhiều so với **"Làm mờ"**, và OCR chạy trên CPU (không dùng GPU). | Nếu ưu tiên tốc độ, chuyển cấu hình sang chế độ **"Làm mờ"**; hoặc tắt hẳn tùy chọn "Xóa chữ trong video (OCR)" nếu video không cần xử lý chữ/logo. |
| Bước **Khớp Khẩu Hình (Lip Sync)** báo lỗi hoặc bị bỏ qua | Không đủ VRAM để chạy thêm LatentSync (cần thêm ~8 GB VRAM ngoài phần đã dùng cho các bước trước). | Tắt tùy chọn **"Khớp môi (Lip Sync)"** khi cấu hình video nếu GPU chỉ có đúng 16 GB VRAM và đã bật nhiều tính năng khác cùng lúc. |
| Setup.exe báo **"Không tìm thấy app.7z"** | Hai file `Setup.exe` và `app.7z` không nằm cùng thư mục. | Chép cả hai file vào chung một thư mục, chạy lại `Setup.exe`. |

---

## Không tìm được nguyên nhân?

1. Chạy lại `Kiem-tra-he-thong.bat`, xem toàn bộ `preflight_report.txt`.
2. Mở `data\orchestrator.log`, tìm đoạn lỗi gần nhất (thường ở cuối file).
3. Ghi lại: bước nào đang chạy khi lỗi xảy ra, cấu hình đã chọn cho video
   đó (ngôn ngữ, lip sync, OCR, chế độ giọng), và nội dung dòng lỗi — gửi
   các thông tin này cho người hỗ trợ kỹ thuật.
