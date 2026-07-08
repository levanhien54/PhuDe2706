# =============================================================================
# Video Dubbing System — Pack Offline Bundle (Windows)
# Mô tả: Thu thập toàn bộ các file wheel của Python để chuẩn bị cho setup offline
# =============================================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
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
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải build tools (pip/setuptools/wheel) thất bại." }

Write-Step "Tải PyTorch CUDA 11.8 Wheels..."
& $PipExe download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải PyTorch (cu118) wheels thất bại." }

Write-Step "Tải Backend Dependencies..."
& $PipExe download -r "$ProjectRoot\orchestrator\requirements.txt" -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải orchestrator requirements thất bại." }
& $PipExe download -r "$ProjectRoot\whisperx-service\requirements.txt" -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải whisperx-service requirements thất bại." }
# whisperx pins a git HEAD (newer than PyPI 3.8.6); build it into an sdist so the offline
# installer can pull it by name with --pre.
& $PipExe download "git+https://github.com/m-bain/whisperx.git" -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải whisperx (git sdist) thất bại." }
& $PipExe download -r "$ProjectRoot\tts-service\requirements.txt" -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải tts-service requirements thất bại." }
& $PipExe download -r "$ProjectRoot\omnivoice-service\requirements.txt" -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải omnivoice-service requirements thất bại." }
# Các gói phụ thuộc bắt buộc — KHÔNG gộp vllm vào đây: một wheel vllm không resolve được (vd trên
# Windows) sẽ làm pip hủy CẢ lệnh và không tải gói nào, nhưng script vẫn báo thành công.
& $PipExe download demucs einops scipy openmim huggingface_hub diffusers -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Fail "Tải các gói phụ thuộc mở rộng (demucs/einops/scipy/openmim/huggingface_hub/diffusers) thất bại." }
# vLLM tách riêng, best-effort (mirror setup_native.ps1): chỉ cảnh báo nếu tải lỗi.
Write-Step "Tải vLLM (tuỳ chọn - thay thế Ollama, best-effort)..."
& $PipExe download vllm -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Warn "Không tải được vLLM wheel — bỏ qua (máy đích sẽ dùng Ollama làm LLM_BACKEND)." }

Write-Step "Tải MMCV Wheel..."
& $PipExe download "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html -d $OfflineDir
if ($LASTEXITCODE -ne 0) { Write-Warn "Không tải được mmcv wheel — bỏ qua (ProPainter có thể không hoạt động trên máy đích)." }

if (Test-Path "$ProjectRoot\models\latentsync\requirements.txt") {
    Write-Step "Tải LatentSync Dependencies..."
    & $PipExe download -r "$ProjectRoot\models\latentsync\requirements.txt" -d $OfflineDir
    if ($LASTEXITCODE -ne 0) { Write-Warn "Không tải được một số phụ thuộc LatentSync — bỏ qua (LatentSync tuỳ chọn)." }
}

Write-OK "Thu thập Python wheels thành công tại $OfflineDir!"
Write-Host "Bây giờ bạn có thể nén thư mục dự án này (BỎ QUA thư mục venv, data/input, data/output, data/temp) để copy sang máy chủ mới." -ForegroundColor Yellow
