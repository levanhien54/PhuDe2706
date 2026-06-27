# =============================================================================
# Video Dubbing System — One-Command Setup (Windows PowerShell)
# Chạy lệnh này một lần trên máy mới để tải toàn bộ models và images.
# Yêu cầu: Docker Desktop với GPU support (NVIDIA Container Toolkit)
# =============================================================================

param(
    [string]$LlmModel   = "qwen2.5:14b",
    [string]$VramProfile = "16gb",
    [switch]$WithLipsync = $false,
    [switch]$SkipPull    = $false
)

# $ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; exit 1 }

Set-Location $ProjectRoot

# ------------------------------------------------------------------
# 1. Kiểm tra prerequisites
# ------------------------------------------------------------------
Write-Step "Kiểm tra prerequisites"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "Docker chưa được cài. Tải tại: https://docs.docker.com/desktop/windows/"
}
Write-OK "Docker found: $(docker --version)"

$oldErr = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$gpuCheck = docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi 2>&1
$ErrorActionPreference = $oldErr
if ($LASTEXITCODE -ne 0) {
    Write-Warn "GPU không khả dụng hoặc NVIDIA Container Toolkit chưa cài."
    Write-Warn "Hệ thống sẽ chạy bằng CPU (chậm hơn nhiều)."
    Write-Warn "Hướng dẫn cài: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
} else {
    Write-OK "NVIDIA GPU khả dụng."
}

# ------------------------------------------------------------------
# 2. Tạo file .env nếu chưa có
# ------------------------------------------------------------------
Write-Step "Cấu hình môi trường"

if (-not (Test-Path "$ProjectRoot\.env")) {
    Copy-Item "$ProjectRoot\orchestrator\.env.example" "$ProjectRoot\.env"
    # Ghi đè các giá trị từ tham số
    (Get-Content "$ProjectRoot\.env") `
        -replace "LLM_MODEL=.*",    "LLM_MODEL=$LlmModel" `
        -replace "VRAM_PROFILE=.*", "VRAM_PROFILE=$VramProfile" |
        Set-Content "$ProjectRoot\.env"
    Write-OK ".env tạo từ .env.example (LLM=$LlmModel, VRAM=$VramProfile)"
} else {
    Write-OK ".env đã tồn tại — giữ nguyên."
}

# ------------------------------------------------------------------
# 3. Tạo thư mục models
# ------------------------------------------------------------------
Write-Step "Tạo thư mục models"

$dirs = @(
    "models\ollama",
    "models\whisper",
    "models\demucs",
    "models\tts",
    "models\omnivoice",
    "models\lipsync",
    "data\input",
    "data\output",
    "data\temp"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\$d" | Out-Null
}
Write-OK "Thư mục models/ và data/ sẵn sàng."

# ------------------------------------------------------------------
# 4. Pull tất cả Docker images
# ------------------------------------------------------------------
if (-not $SkipPull) {
    Write-Step "Kéo Docker images (có thể mất 10-30 phút lần đầu)"

    $profiles = if ($WithLipsync) { "--profile lipsync" } else { "" }
    $pullCmd = "docker compose $profiles pull"
    Write-Host "  Chạy: $pullCmd"
    Invoke-Expression $pullCmd
    if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose pull thất bại." }
    Write-OK "Tất cả images đã được kéo."
} else {
    Write-Warn "Bỏ qua bước pull images (--SkipPull)."
}

# ------------------------------------------------------------------
# 5. Tải LLM model qua Ollama
# ------------------------------------------------------------------
Write-Step "Tải LLM model: $LlmModel (~8-15 GB)"

Write-Host "  Khởi động Ollama container tạm..."
docker compose up -d ollama
Start-Sleep -Seconds 10

# Cho ollama healthy
$tries = 0
do {
    Start-Sleep -Seconds 5
    $health = docker inspect --format="{{.State.Health.Status}}" ai_dubbing_ollama 2>&1
    $tries++
    Write-Host "  Ollama status: $health ($tries/12)"
} while ($health -ne "healthy" -and $tries -lt 12)

if ($health -ne "healthy") {
    Write-Warn "Ollama chua healthy sau 60s - thu pull model truc tiep..."
}

docker exec ai_dubbing_ollama ollama pull $LlmModel
if ($LASTEXITCODE -ne 0) { Write-Fail "Không thể tải model $LlmModel." }
Write-OK "LLM model $LlmModel đã tải vào models/ollama/"

# ------------------------------------------------------------------
# 6. Tải Whisper model (large-v3 ~3GB)
# ------------------------------------------------------------------
# Write-Step "Tai Whisper Large-v3 model (~3 GB)"
# Write-Host "  Khoi dong WhisperX container tam de pre-download model..."
# docker compose up -d whisperx
# Start-Sleep -Seconds 15
# $warmupBody = '{"audio_url":"http://example.com/test.wav"}'
# $tries = 0
# do {
#     Start-Sleep -Seconds 10
#     try {
#         $resp = Invoke-WebRequest -Uri "http://localhost:8001/health" -Method GET -TimeoutSec 5 -ErrorAction SilentlyContinue
#         if ($resp.StatusCode -eq 200) { break }
#     } catch {}
#     $tries++
#     Write-Host "  Cho WhisperX... ($tries/18)"
# } while ($tries -lt 18)
# Write-OK "WhisperX san sang. Model Whisper da duoc cache vao models/whisper/"

# ------------------------------------------------------------------
# 7. Tải Demucs model (tự động khi container khởi động)
# ------------------------------------------------------------------
Write-Step "Tải Demucs htdemucs model (~80 MB)"

docker compose up -d demucs
Start-Sleep -Seconds 5

# Kích hoạt demucs để tải model về
docker exec ai_dubbing_demucs python -c "
import torch
from demucs.pretrained import get_model
get_model('htdemucs')
print('Demucs model downloaded.')
" 2>&1
Write-OK "Demucs model đã tải vào models/demucs/"

# ------------------------------------------------------------------
# 8. Tải OmniVoice model (tự động lần đầu dùng)
# ------------------------------------------------------------------
Write-Step "Khởi động OmniVoice để pre-download model (~2 GB)"

docker compose up -d omnivoice
$tries = 0
do {
    Start-Sleep -Seconds 10
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:3900/health" -Method GET -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) { break }
    } catch {}
    $tries++
    Write-Host "  Chờ OmniVoice... ($tries/18)"
} while ($tries -lt 18)
Write-OK "OmniVoice model đã tải vào models/omnivoice/"

# ------------------------------------------------------------------
# 9. Dừng tất cả containers tạm (chỉ để download)
# ------------------------------------------------------------------
Write-Step "Dừng containers tạm"
docker compose down
Write-OK "Tất cả containers đã dừng."

# ------------------------------------------------------------------
# 10. Tóm tắt
# ------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " SETUP HOÀN TẤT!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Models đã tải:"
Write-Host "   - LLM       : models\ollama\  ($LlmModel)"
Write-Host "   - Whisper   : models\whisper\ (large-v3)"
Write-Host "   - Demucs    : models\demucs\  (htdemucs)"
Write-Host "   - OmniVoice : models\omnivoice\"
Write-Host ""
Write-Host " Để chạy hệ thống:"
Write-Host "   1. Bỏ video .mp4 vào:  data\input\"
Write-Host "   2. Chạy:               docker compose up"
Write-Host "   3. Kết quả ở:          data\output\"
Write-Host ""
if ($WithLipsync) {
    Write-Host " Lip-sync (LatentSync) đã bật."
    Write-Host "   Chạy với: docker compose --profile lipsync up"
} else {
    Write-Host " Lip-sync: TẮT (chạy với -WithLipsync để bật)"
}
Write-Host ""
Write-Host " Đổi model LLM:    -LlmModel gemma2:27b"
Write-Host " VRAM 24GB:        -VramProfile 24gb"
Write-Host "================================================================" -ForegroundColor Green
