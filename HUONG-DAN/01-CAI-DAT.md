# 01 — Cài đặt

Tài liệu này hướng dẫn cài đặt **Video Dubbing** trên một máy Windows mới
(máy nhận bản đóng gói `Setup.exe` + `app.7z`). Ứng dụng chạy 100% offline
sau khi cài — không cần Internet để dịch, nhận diện giọng nói hay lồng tiếng.

---

## 1. Yêu cầu phần cứng

| Thành phần | Tối thiểu | Ghi chú |
|---|---|---|
| GPU | NVIDIA, **≥ 16 GB VRAM** | RTX 4080/3090/4090 trở lên. Bắt buộc phải là GPU NVIDIA — không hỗ trợ AMD/Intel GPU. |
| Driver GPU | **≥ 452.39** | Driver cũ hơn có thể không tương thích CUDA 11.8 mà bundle sử dụng. |
| Ổ đĩa trống | **≥ 35 GB** | Bundle giải nén ra khoảng 20 GB (models + Python runtime + ffmpeg + Ollama). |
| Hệ điều hành | Windows 10/11, 64-bit | Không hỗ trợ Windows 32-bit hoặc phiên bản cũ hơn Windows 10. |
| RAM | 32 GB trở lên (khuyến nghị) | Máy càng nhiều RAM, xử lý video dài càng ổn định. |

Không cần cài Python, Node.js hay FFmpeg riêng — tất cả đã đóng gói sẵn
trong `app.7z` (venv Python, Python runtime, FFmpeg, Ollama, models).

---

## 2. Chuẩn bị

1. Nhận 2 file từ người đóng gói: **`Setup.exe`** và **`app.7z`**.
2. Đặt **cả hai file trong cùng một thư mục** trên máy đích (ví dụ:
   `Downloads\VideoDubbingSetup\`). `Setup.exe` cần tìm thấy `app.7z`
   ngay bên cạnh nó để giải nén — nếu tách rời hai file, cài đặt sẽ báo lỗi
   "Không tìm thấy app.7z".
3. Đảm bảo ổ đĩa chứa thư mục cài đặt còn ít nhất 35 GB trống.

---

## 3. Các bước cài đặt chi tiết

1. Nhấy đúp vào **`Setup.exe`**.
2. Ở màn hình "Choose Install Location", chọn thư mục muốn cài (mặc định:
   `%LOCALAPPDATA%\VideoDubbing`, ví dụ
   `C:\Users\<ten-may>\AppData\Local\VideoDubbing`). Không cần quyền
   Administrator — cài vào thư mục người dùng hiện tại.
3. Nhấn cài đặt. Trình cài sẽ giải nén `app.7z` (~20 GB) vào thư mục đã
   chọn — bước này **mất vài phút**, tùy tốc độ ổ đĩa.
4. Sau khi giải nén, trình cài tự động:
   - Kiểm tra file `Video Dubbing.exe` đã có trong thư mục cài chưa.
   - Sửa lại đường dẫn Python venv (`venv\pyvenv.cfg`) trỏ đúng vào thư
     mục cài thực tế trên máy này (bước kỹ thuật, tự động, không cần thao tác).
   - Tạo shortcut **"Video Dubbing"** trên Desktop và Start Menu.
5. Khi trình cài báo hoàn tất, đóng cửa sổ cài đặt.

---

## 4. Chạy Preflight & đọc `preflight_report.txt`

Trước khi mở ứng dụng lần đầu, hãy **chạy kiểm tra hệ thống** để chắc chắn
máy đủ điều kiện:

1. Vào thư mục vừa cài đặt, nhấy đúp file **`Kiem-tra-he-thong.bat`**.
2. Một cửa sổ console (nền đen) hiện ra, in kết quả từng mục, mỗi dòng có
   dạng:

   ```
   [PASS] GPU NVIDIA: RTX 4080 (driver 551.23)
   [PASS] VRAM: 16.0 GB — dùng VRAM_PROFILE=16gb.
   [FAIL] Cổng 8000: đang bị chiếm — có thể xung đột khi chạy.
   ```

3. Cuối bảng có dòng tổng kết:
   - **`SẴN SÀNG`** — không có `[FAIL]` nào, có thể mở ứng dụng.
   - **`CHƯA ĐẠT: N lỗi`** — cần xử lý các dòng `[FAIL]` trước khi dùng.
4. Kết quả cũng được lưu lại thành file **`preflight_report.txt`** ngay
   cạnh script, có thể mở lại bất cứ lúc nào để xem hoặc gửi cho người hỗ trợ.
5. Nhấn phím bất kỳ để đóng cửa sổ (script tự `pause` ở cuối).

Các mục được kiểm tra: hệ điều hành, GPU + driver, VRAM, dung lượng đĩa
trống, các cổng mạng (8000, 8001, 9880, 3900, 11434, 5173), và (nếu chạy
trong thư mục đã cài) tính toàn vẹn của bundle — các file/model bắt buộc.

### Xử lý từng trường hợp `[FAIL]`

| Mục báo lỗi | Nguyên nhân | Cách khắc phục |
|---|---|---|
| **GPU NVIDIA** | Máy không có GPU NVIDIA, hoặc chưa cài driver — không tìm thấy `nvidia-smi`. | Cắm/kiểm tra GPU NVIDIA vật lý; cài driver NVIDIA mới nhất từ trang chủ NVIDIA rồi khởi động lại máy. |
| **Driver GPU** *(cảnh báo)* | Driver hiện tại cũ hơn 452.39, có thể không chạy được CUDA 11.8. | Vào [nvidia.com/drivers](https://www.nvidia.com/drivers) tải bản mới nhất cho đúng dòng GPU, cài rồi khởi động lại. |
| **VRAM** | GPU có VRAM dưới 16 GB — không đủ để chạy các model AI. | Cần đổi sang GPU ≥ 16 GB VRAM. Không có cách giảm yêu cầu này (đã là ngưỡng tối thiểu của hệ thống). |
| **Dung lượng đĩa** | Ổ chứa thư mục cài còn dưới 35 GB trống. | Giải phóng bớt dung lượng (xóa file rác, chuyển bớt dữ liệu sang ổ khác), hoặc chọn cài vào ổ đĩa khác còn nhiều dung lượng hơn. |
| **Cổng (8000/8001/9880/3900/11434/5173)** | Có chương trình khác đang chiếm dụng cổng mạng mà Video Dubbing cần dùng. | Đóng chương trình đang chiếm cổng đó (ví dụ Ollama đang chạy sẵn, server khác đang lắng nghe cùng cổng), rồi chạy lại `Kiem-tra-he-thong.bat`. Chi tiết cách tìm tiến trình chiếm cổng: xem file `03-XU-LY-SU-CO.md`. |
| **Bundle: <tên file/thư mục>** | Bản `app.7z` giải nén thiếu file hoặc model (gói bị lỗi/cắt ngắn khi tải/copy). | Xóa thư mục đã cài, tải lại `Setup.exe` + `app.7z` (đảm bảo copy đủ, không bị ngắt giữa chừng), cài lại từ đầu. |
| **Hệ điều hành** | Máy không phải Windows 10/11 64-bit. | Cần nâng cấp lên Windows 10/11 64-bit — hệ thống không hỗ trợ Windows cũ hơn hoặc bản 32-bit. |

Sau khi xử lý xong các mục `[FAIL]`, chạy lại `Kiem-tra-he-thong.bat` để
xác nhận kết quả `SẴN SÀNG` trước khi mở "Video Dubbing".

---

## 5. Mở ứng dụng lần đầu

Xem tiếp file **`02-SU-DUNG.md`** để biết màn hình khởi động, cách thêm
video và sử dụng các tính năng.
