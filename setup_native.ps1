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
Write-Step "Kiểm tra yêu cầu hệ thống (Pre-flight Checks)"

# 1.1 OS Architecture
if ([Environment]::Is64BitOperatingSystem -eq $false) {
    Write-Fail "Hệ điều hành của bạn không phải 64-bit. Hệ thống yêu cầu Windows 64-bit."
}
Write-OK "OS Architecture: 64-bit"

# 1.2 Python Version
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy Python. Vui lòng cài đặt Python 3.10.x và thêm vào PATH."
}
$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pyVersion -lt [version]"3.10") {
    Write-Fail "Phiên bản Python hiện tại là $pyVersion. Hệ thống yêu cầu Python >= 3.10."
}
Write-OK "Python found: v$pyVersion"

# 1.3 Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy Node.js. Vui lòng cài đặt Node.js để chạy Frontend."
}
Write-OK "Node.js found."

# 1.4 FFmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy FFmpeg. Vui lòng cài đặt và thêm FFmpeg vào PATH."
}
Write-OK "FFmpeg found."

# 1.5 Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy Git. Vui lòng cài đặt Git và thêm vào PATH để tải mã nguồn."
}
Write-OK "Git found."

# 1.6 NVIDIA GPU Check
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Fail "Không tìm thấy NVIDIA GPU (hoặc nvidia-smi không nằm trong PATH). Dự án này bắt buộc yêu cầu Card đồ họa NVIDIA có hỗ trợ CUDA để chạy các mô hình AI."
}
$gpuInfo = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gpuInfo)) {
    Write-Fail "Lỗi khi kiểm tra thông tin GPU NVIDIA."
}
$gpuInfo = $gpuInfo.Trim()
Write-OK "NVIDIA GPU found: $gpuInfo"

try {
    $vramStr = ($gpuInfo -split ',')[1].Trim().Replace(" MiB", "")
    $vramMB = [int]$vramStr
    if ($vramMB -lt 8000) {
        Write-Warn "GPU của bạn có $vramMB MB VRAM (< 8GB). Hệ thống vẫn cho phép cài đặt, nhưng một số tính năng nặng có thể báo lỗi hết bộ nhớ (OOM)."
    }
} catch {}

# 1.7 Disk Space Check
$driveName = (Get-Location).Drive.Name
$drive = Get-PSDrive -Name $driveName
$freeSpaceGB = [math]::Round($drive.Free / 1GB, 2)
if ($freeSpaceGB -lt 20) {
    Write-Warn "Ổ đĩa ${driveName}: chỉ còn $freeSpaceGB GB trống. Đề xuất có ít nhất 20GB trống để chứa các trọng số AI."
} else {
    Write-OK "Disk space OK: $freeSpaceGB GB trống trên ${driveName}:"
}

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

# OCR text-detection backend = EasyOCR (CRAFT, pure PyTorch on GPU) — installed via
# orchestrator/requirements.txt. No paddlepaddle needed (it required the broken cuDNN 8).

# 4. Cài đặt các thư viện hệ thống
Write-Step "Cài đặt Backend Dependencies"

# Orchestrator
& $PipExe install @PipArgs -r "$ProjectRoot\orchestrator\requirements.txt"
# WhisperX framework deps + engine (git HEAD online; bundled sdist offline)
& $PipExe install @PipArgs -r "$ProjectRoot\whisperx-service\requirements.txt"
if ($IsOffline) {
    & $PipExe install @PipArgs --pre whisperx
} else {
    & $PipExe install git+https://github.com/m-bain/whisperx.git
}
# TTS (GPT-SoVITS adapter)
& $PipExe install @PipArgs -r "$ProjectRoot\tts-service\requirements.txt"
# OmniVoice (engine TTS mặc định)
& $PipExe install @PipArgs -r "$ProjectRoot\omnivoice-service\requirements.txt"

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
import sys
import urllib.request

def dl(url, path):
    # Skip only if a non-empty file already exists. Download to a .part temp and atomically
    # replace on success so an interrupted download never leaves a truncated file behind that
    # future runs would blindly skip. Raise on failure so the caller can surface it.
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    tmp = path + '.part'
    print(f'Downloading {os.path.basename(path)}...')
    try:
        urllib.request.urlretrieve(url, tmp)
        if os.path.getsize(tmp) == 0:
            raise IOError('file rỗng sau khi tải')
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f'Lỗi khi tải {os.path.basename(path)}: {e}', file=sys.stderr)
        raise

weights_dir = os.path.join(r'$ProjectRoot', 'models', 'propainter', 'weights')
os.makedirs(weights_dir, exist_ok=True)

downloads = [
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/ProPainter.pth', os.path.join(weights_dir, 'ProPainter.pth')),
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/raft-things.pth', os.path.join(weights_dir, 'raft-things.pth')),
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/i3d_rgb_imagenet.pt', os.path.join(weights_dir, 'i3d_rgb_imagenet.pt')),
]
failed = False
for url, path in downloads:
    try:
        dl(url, path)
    except Exception:
        failed = True
if failed:
    sys.exit(1)
"@
& $PythonExe -c $propainter_script
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Tải một số trọng số ProPainter thất bại. ProPainter có thể không hoạt động; hãy chạy lại setup để thử lại."
} else {
    Write-OK "Đã kiểm tra weights ProPainter."
}

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

Write-Host "Kích hoạt tải trước mô hình htdemucs_ft..."
& $PythonExe -c "from demucs.pretrained import get_model; get_model('htdemucs_ft')"
Write-OK "Đã tải htdemucs_ft."

# Tải trước WhisperX model (~3 GB cho large-v3)
Write-Step "Tải trước mô hình WhisperX (large-v3, ~3GB)"
$whisperModel = if ($env:WHISPER_MODEL) { $env:WHISPER_MODEL } else { "large-v3" }
$whisper_dl_script = @"
import os, sys
model_name = r'$whisperModel'
model_dir  = os.path.join(r'$ProjectRoot', 'models', 'whisper')
os.makedirs(model_dir, exist_ok=True)
print(f'Downloading WhisperX model [{model_name}] to {model_dir} ...')
try:
    import whisperx
    m = whisperx.load_model(model_name, 'cpu', compute_type='int8', download_root=model_dir)
    del m
    print('WhisperX model ready.')
except Exception as e:
    print(f'Canh bao: Khong the tai WhisperX model: {e}', file=sys.stderr)
    print('Model se duoc tai tu dong lan dau su dung.', file=sys.stderr)
"@
& $PythonExe -c $whisper_dl_script
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Không thể tải trước WhisperX model. Model sẽ tự tải khi sử dụng lần đầu."
} else {
    Write-OK "Đã tải WhisperX model."
}

# Tải GPT-SoVITS pretrained models
Write-Step "Kiểm tra và tải GPT-SoVITS Pretrained Models"
$gptSoVitsPretrainedDir = "$ProjectRoot\GPT-SoVITS\GPT_SoVITS\pretrained_models"
if (-not (Test-Path "$gptSoVitsPretrainedDir\chinese-roberta-wwm-ext-large")) {
    Write-Host "Đang tải GPT-SoVITS Pretrained Models (sẽ tốn thời gian)..." -ForegroundColor Yellow
    $gpt_script = @"
import os
import sys
import urllib.request
import zipfile

def dl(url, path):
    # Download to a .part temp and atomically replace on success so an interrupted download
    # never leaves a truncated zip behind; raise on failure so the caller can surface it.
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    tmp = path + '.part'
    print(f'Downloading {os.path.basename(path)}...')
    try:
        urllib.request.urlretrieve(url, tmp)
        if os.path.getsize(tmp) == 0:
            raise IOError('file rỗng sau khi tải')
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f'Lỗi khi tải {os.path.basename(path)}: {e}', file=sys.stderr)
        raise

zip_path = os.path.join(r'$ProjectRoot', 'GPT-SoVITS', 'pretrained_models.zip')
try:
    dl('https://huggingface.co/lj1995/GPT-SoVITS/resolve/main/pretrained_models.zip', zip_path)
except Exception:
    sys.exit(1)

if os.path.exists(zip_path):
    print('Extracting pretrained models...')
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(os.path.join(r'$ProjectRoot', 'GPT-SoVITS'))
    except zipfile.BadZipFile as e:
        print(f'File zip hỏng: {e}', file=sys.stderr)
        os.remove(zip_path)
        sys.exit(1)
    os.remove(zip_path)
"@
    & $PythonExe -c $gpt_script
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Không thể tải GPT-SoVITS Pretrained Models. TTS có thể không hoạt động."
    } else {
        Write-OK "Đã tải GPT-SoVITS Pretrained Models."
    }
} else {
    Write-OK "GPT-SoVITS Pretrained Models đã tồn tại."
}

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
