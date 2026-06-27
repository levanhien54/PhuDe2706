# Di chuyển toàn bộ dự án sang server (Windows → Windows, qua Internet)

Đường ống truyền file P2P nhanh nhất cho ~20GB+ (kể cả `models/`) qua Internet, không cần mở port hay IP public.

**Công cụ chính: [croc](https://github.com/schollz/croc)** — P2P xuyên NAT, đa luồng TCP, mã hóa end-to-end (PAKE), tự resume khi đứt mạng. Chạy được Windows ↔ Windows.

**Dự phòng: rsync over SSH** — tốt cho đồng bộ lại nhiều lần (delta, resume). Xem mục 4.

---

## 0. Cách dễ nhất: giao diện click (khuyến nghị)

Double-click **`migrate\Migrate.bat`** để mở giao diện:
- Tự kiểm tra croc, có nút **Cài croc** (qua winget) nếu thiếu.
- Khung **GỬI** (máy nguồn): tick "Dọn" → bấm **Bắt đầu gửi** → code phrase hiện to và tự copy vào clipboard.
- Khung **NHẬN** (server): dán code phrase, chọn thư mục lưu → bấm **Bắt đầu nhận**.
- Khung log đen hiển thị tiến độ trực tiếp.

Phần còn lại của tài liệu là cách làm bằng dòng lệnh (nếu thích).

---

## 1. Cài croc (cả MÁY NGUỒN lẫn SERVER)

```powershell
winget install schollz.croc
# hoặc: scoop install croc   |   choco install croc
# hoặc tải binary: https://github.com/schollz/croc/releases
```

Kiểm tra: `croc --version`

---

## 2. Gửi — chạy trên MÁY NGUỒN (máy hiện tại)

```powershell
cd C:\Users\sonson\Desktop\PhuDe27.06
.\migrate\send.ps1 -Clean
```

- `-Clean`: dọn `data/temp`, `data/output`, `frontend/node_modules` trước khi gửi (giảm dung lượng; các thứ này tái tạo được).
- Mặc định **không gửi `.git`** (code đã có trên GitHub). Thêm `-IncludeGit` nếu muốn giữ lịch sử git.

croc sẽ in ra một **code phrase**, ví dụ:
```
Code is: 8421-mango-river-piano
On the other computer run: croc 8421-mango-river-piano
```
Đọc dòng đó cho người ở server.

---

## 3. Nhận — chạy trên SERVER

```powershell
# Tạo thư mục đích và nhận vào đó
mkdir C:\PhuDe27.06
cd C:\PhuDe27.06
croc --yes 8421-mango-river-piano      # thay bằng code phrase thật
```

- `--yes`: tự đồng ý, không hỏi.
- Nếu mạng đứt giữa chừng: chạy lại đúng lệnh `croc <code>` — croc **resume** từ chỗ dở.
- File về thẳng thư mục hiện tại.

---

## 4. (Dự phòng) rsync over SSH — đồng bộ lại nhiều lần

Server đã có OpenSSH. Từ máy nguồn (cần rsync; trên Windows dùng Git Bash hoặc WSL):

```bash
# -a giữ thuộc tính, -z nén (BỎ -z cho models vì đã nén sẵn), -P hiện tiến độ + resume,
# --partial giữ phần đã truyền khi đứt
rsync -aP --partial \
  --exclude 'data/temp/*' --exclude 'data/output/*' \
  --exclude 'frontend/node_modules' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.git' \
  /c/Users/sonson/Desktop/PhuDe27.06/ \
  user@SERVER_HOST:/c/PhuDe27.06/
```

Chạy lại lệnh trên bất cứ lúc nào để đồng bộ phần thay đổi (rsync chỉ truyền delta). Nhanh nhất khi chỉ models thay đổi ít.

> Lưu ý: rsync 1 luồng qua Internet thường chậm hơn croc đa luồng cho lần đầu 20GB. Dùng croc cho lần đầu, rsync cho các lần cập nhật sau.

---

## 5. Sau khi truyền xong — dựng trên server

```powershell
cd C:\PhuDe27.06

# Nếu KHÔNG gửi .git và muốn có git: clone đè code (giữ models đã truyền)
# git clone https://github.com/levanhien54/PhuDe2706 tmp; robocopy tmp . /E /XD models data; rmdir /S /Q tmp

# Build các service cục bộ (whisperx, tts) + khởi động — xem DEPLOY.md
docker compose build
docker compose up -d
docker compose logs -f whisperx orchestrator
```

Kiểm tra models đã sang đủ:
```powershell
Get-ChildItem C:\PhuDe27.06\models -Directory   # ollama, whisper, demucs, omnivoice, tts, lipsync
```

---

## 6. Mẹo tối ưu tốc độ

- **Đừng nén models**: `send.ps1` đã dùng `--no-compress`; rsync bỏ `-z`. Weights đã nén, nén lại chỉ tốn CPU.
- **Có dây mạng / gần relay**: croc dùng relay công cộng mặc định. Nếu hai máy cùng vùng, tốc độ giới hạn bởi băng thông upload máy nguồn.
- **Tự dựng relay riêng** (nếu muốn nhanh & riêng tư hơn): chạy `croc relay` trên một VPS, rồi cả hai bên dùng `--relay "VPS_IP:9009"`.
- **Truyền song song nhiều phần**: nếu chỉ models lớn, có thể croc send riêng từng thư mục con của `models/` ở nhiều cửa sổ để tận dụng băng thông.
