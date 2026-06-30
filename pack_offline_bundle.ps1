# =============================================================================
# Video Dubbing System — Pack Offline Bundle (Windows)
# Mô tả: Thu thập toàn bộ các file wheel của Python để chuẩn bị cho setup offline
# =============================================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; exit 1 }

$PipExe = "$ProjectRoot\venv\Scripts\pip.exe"
if (-not (Test-Path $PipExe)) {
    Write-Fail "Không tìm thấy venv nội bộ. Hãy chạy setup_native.ps1 trên máy này trước khi đóng gói!"
}

$OfflineDir = "$ProjectRoot\offline_wheels"
if (-not (Test-Path $OfflineDir)) {
    New-Item -ItemType Directory -Force -Path $OfflineDir | Out-Null
}

Write-Step "Tải build tools (pip/setuptools/wheel — cần để build các sdist như demucs, dora-search, whisperx khi cài offline)..."
& $PipExe download pip setuptools wheel -d $OfflineDir

Write-Step "Tải PyTorch CUDA 11.8 Wheels..."
& $PipExe download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -d $OfflineDir

Write-Step "Tải Backend Dependencies..."
& $PipExe download -r "$ProjectRoot\orchestrator\requirements.txt" -d $OfflineDir
& $PipExe download -r "$ProjectRoot\whisperx-service\requirements.txt" -d $OfflineDir
# whisperx pins a git HEAD (newer than PyPI 3.8.6); build it into an sdist so the offline
# installer can pull it by name with --pre.
& $PipExe download "git+https://github.com/m-bain/whisperx.git" -d $OfflineDir
& $PipExe download -r "$ProjectRoot\tts-service\requirements.txt" -d $OfflineDir
& $PipExe download -r "$ProjectRoot\omnivoice-service\requirements.txt" -d $OfflineDir
& $PipExe download demucs vllm einops scipy openmim huggingface_hub diffusers -d $OfflineDir

Write-Step "Tải MMCV Wheel..."
& $PipExe download "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html -d $OfflineDir

if (Test-Path "$ProjectRoot\models\latentsync\requirements.txt") {
    Write-Step "Tải LatentSync Dependencies..."
    & $PipExe download -r "$ProjectRoot\models\latentsync\requirements.txt" -d $OfflineDir
}

Write-OK "Thu thập Python wheels thành công tại $OfflineDir!"
Write-Host "Bây giờ bạn có thể nén thư mục dự án này (BỎ QUA thư mục venv, data/input, data/output, data/temp) để copy sang máy chủ mới." -ForegroundColor Yellow
