# =============================================================================
# Video Dubbing System — Native Setup (Không dùng Docker)
# Yêu cầu trước khi chạy: Python 3.10+, Node.js, FFmpeg, NVIDIA GPU
# =============================================================================

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; exit 1 }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

# 1. Kiểm tra yêu cầu hệ thống
Write-Step "Kiểm tra yêu cầu hệ thống"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy Python. Vui lòng cài đặt Python 3.10 hoặc cao hơn và thêm vào PATH."
}
Write-OK "Python found."

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy Node.js. Vui lòng cài đặt Node.js để chạy Frontend."
}
Write-OK "Node.js found."

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy FFmpeg. Vui lòng cài đặt và thêm FFmpeg vào PATH."
}
Write-OK "FFmpeg found."

# 2. Thiết lập Môi trường Python (venv)
Write-Step "Thiết lập Python Virtual Environment"

if (-not (Test-Path "$ProjectRoot\venv")) {
    Write-Host "Đang tạo venv mới..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Tạo venv thất bại." }
}
Write-OK "Venv đã sẵn sàng tại .\venv"

$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"
$PipExe = "$ProjectRoot\venv\Scripts\pip.exe"

$OfflineDir = "$ProjectRoot\offline_wheels"
$IsOffline = Test-Path $OfflineDir

if ($IsOffline) {
    Write-Host "Phát hiện thư mục offline_wheels, kích hoạt chế độ Cài đặt Offline (Siêu tốc)..." -ForegroundColor Yellow
    $PipArgs = @('--no-index', "--find-links=$OfflineDir")
} else {
    $PipArgs = @()
}

# Cập nhật pip
& $PythonExe -m pip install @PipArgs --upgrade pip

# 3. Cài đặt PyTorch với CUDA (mặc định cu118 để tương thích WhisperX)
Write-Step "Cài đặt PyTorch (CUDA 11.8)"
if ($IsOffline) {
    & $PipExe install @PipArgs torch torchvision torchaudio
} else {
    & $PipExe install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
}
if ($LASTEXITCODE -ne 0) { Write-Fail "Cài đặt PyTorch thất bại." }

# 4. Cài đặt các thư viện hệ thống
Write-Step "Cài đặt Backend Dependencies"

# Orchestrator
& $PipExe install @PipArgs -r "$ProjectRoot\orchestrator\requirements.txt"
# WhisperX
& $PipExe install @PipArgs -r "$ProjectRoot\whisperx-service\requirements.txt"
# TTS
& $PipExe install @PipArgs -r "$ProjectRoot\tts-service\requirements.txt"

# Cài đặt Demucs cục bộ để hỗ trợ native
& $PipExe install @PipArgs demucs

# Cài đặt vLLM (Tuỳ chọn)
Write-Step "Cài đặt vLLM (Tuỳ chọn - Thay thế Ollama)"
Write-Host "Lưu ý: Trên Windows Native, cài đặt vLLM có thể gặp lỗi (đặc biệt liên quan đến flash-attn). Hệ thống sẽ tự dùng Ollama nếu vLLM không khả dụng." -ForegroundColor Yellow
& $PipExe install @PipArgs vllm
if ($LASTEXITCODE -ne 0) { 
    Write-Warn "Không thể cài đặt vLLM. Hãy đảm bảo dùng Ollama làm LLM_BACKEND." 
} else {
    Write-OK "Đã cài đặt vLLM thành công."
}

# Cài đặt thư viện cho ProPainter (Tuỳ chọn)
Write-Step "Cài đặt phụ thuộc cho ProPainter"
& $PipExe install @PipArgs einops scipy openmim
Write-Host "Đang cài đặt mmcv..."
if ($IsOffline) {
    & $PipExe install @PipArgs "mmcv>=2.0.0"
} else {
    & $PythonExe -m mim install "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html
}
if ($LASTEXITCODE -ne 0) { 
    Write-Warn "Cài đặt mmcv thất bại. Tính năng ProPainter có thể không hoạt động." 
}

# 5. Khởi tạo thư mục và tải model Demucs sẵn
Write-Step "Tạo thư mục models và cấu hình"
$dirs = @("models\ollama", "models\whisper", "models\demucs", "models\tts", "models\propainter", "data\input", "data\output", "data\temp")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\$d" | Out-Null
}

if (-not (Test-Path "$ProjectRoot\models\propainter\inference_propainter.py")) {
    Write-Host "Đang tải mã nguồn ProPainter..."
    git clone https://github.com/sczhou/ProPainter.git "$ProjectRoot\models\propainter"
}

Write-Host "Kích hoạt tải trọng số ProPainter (Khoảng 2GB)..."
$propainter_script = @"
import os
import urllib.request

def dl(url, path):
    if not os.path.exists(path):
        print(f'Downloading {os.path.basename(path)}...')
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as e:
            print(f'Lỗi khi tải {path}: {e}')

weights_dir = os.path.join(r'$ProjectRoot', 'models', 'propainter', 'weights')
os.makedirs(weights_dir, exist_ok=True)

dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/ProPainter.pth', os.path.join(weights_dir, 'ProPainter.pth'))
dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/raft-things.pth', os.path.join(weights_dir, 'raft-things.pth'))
dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/i3d_rgb_imagenet.pt', os.path.join(weights_dir, 'i3d_rgb_imagenet.pt'))
"@
& $PythonExe -c $propainter_script
Write-OK "Đã kiểm tra weights ProPainter."

if (-not (Test-Path "$ProjectRoot\models\latentsync\scripts\inference.py")) {
    Write-Host "Đang tải mã nguồn LatentSync (Lip-Sync)..."
    git clone https://github.com/bytedance/LatentSync.git "$ProjectRoot\models\latentsync"
    # Cài đặt dependencies của LatentSync
    & $PipExe install @PipArgs -r "$ProjectRoot\models\latentsync\requirements.txt"
    & $PipExe install @PipArgs huggingface_hub diffusers
} else {
    Write-OK "Phát hiện mã nguồn LatentSync đã có sẵn (Offline/Cache), bỏ qua git clone."
}

Write-Host "Kích hoạt tải trọng số LatentSync (có thể mất thời gian do file lớn)..."
$hf_script = @"
import os
from huggingface_hub import snapshot_download
target_dir = os.path.join(r'$ProjectRoot', 'models', 'latentsync', 'checkpoints')
os.makedirs(target_dir, exist_ok=True)
if not os.path.exists(os.path.join(target_dir, 'latentsync_unet.pt')):
    print('Downloading LatentSync weights from huggingface...')
    snapshot_download(repo_id='ByteDance/LatentSync', local_dir=target_dir)
"@
& $PythonExe -c $hf_script
Write-OK "Đã kiểm tra weights LatentSync."

Write-Host "Kích hoạt tải trước mô hình htdemucs..."
& $PythonExe -c "from demucs.pretrained import get_model; get_model('htdemucs')"
Write-OK "Đã tải htdemucs."

if (-not (Test-Path "$ProjectRoot\.env")) {
    Copy-Item "$ProjectRoot\orchestrator\.env.example" "$ProjectRoot\.env"
}

# 6. Cài đặt Frontend
Write-Step "Cài đặt Frontend Dependencies"
Set-Location "$ProjectRoot\frontend"
npm install
if ($LASTEXITCODE -ne 0) { Write-Fail "Lỗi khi chạy npm install." }
Set-Location $ProjectRoot

Write-Step "SETUP HOÀN TẤT!"
Write-Host "Chạy .\run_native.ps1 để khởi động hệ thống." -ForegroundColor Green
