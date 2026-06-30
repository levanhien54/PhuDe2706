# =============================================================================
# Video Dubbing System — Offline Setup (Cài đặt không cần Internet)
# Dành cho máy chủ mới sau khi đã copy file ZIP từ máy cũ.
# Yêu cầu: Đã cài Python 3.10+, Node.js, FFmpeg, và có thư mục offline_wheels
# =============================================================================

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; exit 1 }

$OfflineDir = "$ProjectRoot\offline_wheels"
if (-not (Test-Path $OfflineDir)) {
    Write-Fail "Không tìm thấy thư mục offline_wheels. Xin đảm bảo đã chạy pack_offline_bundle trên máy cũ và chép đầy đủ."
}

# 1. Thiết lập Môi trường Python (venv)
Write-Step "Thiết lập Python Virtual Environment"

if (-not (Test-Path "$ProjectRoot\venv")) {
    Write-Host "Đang tạo venv mới..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Tạo venv thất bại." }
}
Write-OK "Venv đã sẵn sàng tại .\venv"

$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"
$PipExe = "$ProjectRoot\venv\Scripts\pip.exe"

# 2. Cài đặt các thư viện từ thư mục Offline Wheels
Write-Step "Cài đặt Backend từ Offline Wheels (Siêu Tốc)"

$BasePipArgs = @('--no-index', "--find-links=$OfflineDir")

# PyTorch
Write-Host "Cài đặt PyTorch..."
& $PipExe install @BasePipArgs torch torchvision torchaudio

# Dịch vụ
Write-Host "Cài đặt Orchestrator..."
& $PipExe install @BasePipArgs -r "$ProjectRoot\orchestrator\requirements.txt"
Write-Host "Cài đặt WhisperX (engine từ sdist đã đóng gói, không dùng git)..."
& $PipExe install @BasePipArgs -r "$ProjectRoot\whisperx-service\requirements.txt"
& $PipExe install @BasePipArgs --pre whisperx
Write-Host "Cài đặt TTS..."
& $PipExe install @BasePipArgs -r "$ProjectRoot\tts-service\requirements.txt"
Write-Host "Cài đặt OmniVoice (engine mặc định)..."
& $PipExe install @BasePipArgs -r "$ProjectRoot\omnivoice-service\requirements.txt"

# Phụ thuộc khác
Write-Host "Cài đặt các gói phụ thuộc mở rộng..."
& $PipExe install @BasePipArgs demucs vllm einops scipy huggingface_hub diffusers
Write-Host "Cài đặt mmcv (cần cho ProPainter)..."
& $PipExe install @BasePipArgs "mmcv>=2.0.0"

# LatentSync
if (Test-Path "$ProjectRoot\models\latentsync\requirements.txt") {
    Write-Host "Cài đặt phụ thuộc LatentSync..."
    & $PipExe install @BasePipArgs -r "$ProjectRoot\models\latentsync\requirements.txt"
}

Write-OK "Đã cài đặt xong thư viện Backend."

# 3. Môi trường và Models
Write-Step "Kiểm tra cấu hình"

if (-not (Test-Path "$ProjectRoot\.env")) {
    Copy-Item "$ProjectRoot\orchestrator\.env.example" "$ProjectRoot\.env"
}

# 4. Cài đặt Frontend
Write-Step "Cài đặt Frontend"
Set-Location "$ProjectRoot\frontend"
npm install
if ($LASTEXITCODE -ne 0) { Write-Fail "Lỗi khi chạy npm install." }
Set-Location $ProjectRoot

Write-Step "OFFLINE SETUP HOÀN TẤT!"
Write-Host "Cài đặt thư viện siêu tốc thành công!" -ForegroundColor Green
Write-Host ""
Write-Host "LƯU Ý QUAN TRỌNG VỀ OLLAMA (LLM DỊCH THUẬT):" -ForegroundColor Yellow
Write-Host "Hệ thống cần Ollama để chạy mô hình dịch thuật Qwen2.5."
Write-Host "1. Tải và cài đặt Ollama từ: https://ollama.com/download/OllamaSetup.exe"
Write-Host "2. Tắt hẳn ứng dụng Ollama ở thanh Taskbar (góc dưới bên phải màn hình)."
Write-Host "3. Chạy script .\run_native.ps1 - Hệ thống sẽ tự động liên kết với model đã tải sẵn."
Write-Host ""
Write-Host "==> Hãy chạy: .\run_native.ps1 để khởi động toàn bộ hệ thống!" -ForegroundColor Cyan
