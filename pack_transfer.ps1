# Video Dubbing -- Pack Transfer Bundle
# Copy toan bo project sang thu muc dich (USB / o cung / may khac)
# Su dung: .\pack_transfer.ps1 -Dest "D:\VideoDubbing"

param(
    [string]$Dest = "$env:USERPROFILE\Desktop\VideoDubbing-Transfer"
)

$ErrorActionPreference = "Stop"
$Src = $PSScriptRoot

function Step($msg)  { Write-Host "" ; Write-Host "==> $msg" -ForegroundColor Cyan }
function OK($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg)  { Write-Host "  [..] $msg" -ForegroundColor Gray }
function Warn($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  Video Dubbing -- Pack Transfer" -ForegroundColor Magenta
Write-Host "  Nguon : $Src" -ForegroundColor Magenta
Write-Host "  Dich  : $Dest" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# 1. App EXE (portable build tu dist-electron)
Step "Chep App EXE"
$exeSrc = "$Src\dist-electron\Video Dubbing.exe"
if (Test-Path $exeSrc) {
    Copy-Item $exeSrc "$Dest\Video Dubbing.exe" -Force
    $szMB = [math]::Round((Get-Item $exeSrc).Length / 1MB, 1)
    OK "Video Dubbing.exe  ($szMB MB)"
} else {
    Warn "Chua co EXE -- hay chay: npx electron-builder --win portable"
}

# 2. Source code Python (gồm omnivoice-service — engine TTS mặc định)
Step "Chep Source Code Python"
foreach ($svc in @("orchestrator", "whisperx-service", "tts-service", "omnivoice-service", "electron")) {
    if (Test-Path "$Src\$svc") {
        robocopy "$Src\$svc" "$Dest\$svc" /MIR /XD __pycache__ .pytest_cache /XF "*.pyc" "*.pyo" /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        OK $svc
    }
}

# 2b. Frontend (cần cho setup_offline 'npm install' + frontend/dist mà EXE nạp). Bỏ node_modules.
Step "Chep Frontend"
if (Test-Path "$Src\frontend") {
    robocopy "$Src\frontend" "$Dest\frontend" /MIR /XD node_modules /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    OK "frontend"
}

# 2c. GPT-SoVITS (code cho engine TTS thay thế gpt_sovits; bỏ qua nếu không dùng). Có thể rất lớn.
Step "Chep GPT-SoVITS (engine TTS thay thế, tùy chọn)"
if (Test-Path "$Src\GPT-SoVITS") {
    robocopy "$Src\GPT-SoVITS" "$Dest\GPT-SoVITS" /MIR /XD __pycache__ .git /XF "*.pyc" "*.pyo" /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    OK "GPT-SoVITS"
} else {
    Info "Khong co GPT-SoVITS (bo qua - dung omnivoice lam engine mac dinh)"
}

# 2d. Voices -- preset narrator-voice library (clip tham chieu clone theo quoc gia)
Step "Chep thu vien giong doc (voices)"
if (Test-Path "$Src\voices") {
    robocopy "$Src\voices" "$Dest\voices" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    OK "voices"
}

# 3. Models -- Ollama LLM la file lon nhat
Step "Chep Models Ollama - co the mat vai phut"
$ollamaLocal = "$env:USERPROFILE\.ollama\models"
if (Test-Path "$Src\models\ollama") {
    robocopy "$Src\models\ollama" "$Dest\models\ollama" /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    $sz = (Get-ChildItem "$Src\models\ollama" -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\ollama  ({0:N1} GB)" -f ($sz/1GB))
} elseif (Test-Path $ollamaLocal) {
    Info "Dang chep model tu $ollamaLocal vao package..."
    robocopy $ollamaLocal "$Dest\models\ollama" /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    $sz = (Get-ChildItem $ollamaLocal -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\ollama  ({0:N1} GB)" -f ($sz/1GB))
} else {
    Info "Khong co models\ollama"
}

Step "Chep Models HuggingFace (Whisper/TTS) - co the mat vai phut"
$hfLocal = "$env:USERPROFILE\.cache\huggingface\hub"
if (Test-Path "$Src\models\huggingface") {
    robocopy "$Src\models\huggingface" "$Dest\models\huggingface" /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    $sz = (Get-ChildItem "$Src\models\huggingface" -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\huggingface  ({0:N1} GB)" -f ($sz/1GB))
} elseif (Test-Path $hfLocal) {
    Info "Dang chep model tu $hfLocal vao package..."
    robocopy $hfLocal "$Dest\models\huggingface" /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    $sz = (Get-ChildItem $hfLocal -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\huggingface  ({0:N1} GB)" -f ($sz/1GB))
} else {
    Info "Khong co models\huggingface"
}

# Cac model khac (demucs, whisper, latentsync, v.v.)
Step "Chep Models khac"
foreach ($m in @("demucs","whisper","latentsync","propainter","tts","omnivoice","easyocr","lipsync")) {
    $mp = "$Src\models\$m"
    if (Test-Path $mp) {
        $sz = (Get-ChildItem $mp -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        if ($sz -gt 0) {
            robocopy $mp "$Dest\models\$m" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
            OK ("models\$m  ({0:N0} MB)" -f ($sz/1MB))
        }
    }
}

# 4. Config & Scripts
Step "Chep Config, Scripts va Offline Wheels"
$files = @(".env", "icon.ico", "setup_native.ps1", "setup_offline.ps1",
           "run_native.ps1", "pack_offline_bundle.ps1", "pack_transfer.ps1",
           "build-electron.ps1")
foreach ($f in $files) {
    if (Test-Path "$Src\$f") {
        Copy-Item "$Src\$f" "$Dest\$f" -Force
        OK $f
    }
}

if (Test-Path "$Src\offline_wheels") {
    robocopy "$Src\offline_wheels" "$Dest\offline_wheels" /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    OK "offline_wheels"
} else {
    Warn "Khong co offline_wheels! Moi chay .\pack_offline_bundle.ps1 truoc de dam bao may dich co the cai dat offline."
}

# .env fallback
if (-not (Test-Path "$Dest\.env")) {
    $envEx = "$Src\orchestrator\.env.example"
    if (Test-Path $envEx) {
        Copy-Item $envEx "$Dest\.env"
        Info "Da tao .env tu .env.example"
    }
}

# 5. Tao cau truc thu muc can thiet
Step "Tao cau truc thu muc"
foreach ($d in @("data\input","data\output","data\temp","models\whisper",
                 "models\demucs","models\tts","models\latentsync")) {
    New-Item -ItemType Directory -Force -Path "$Dest\$d" | Out-Null
}
OK "Structure ready"

# 6. Tong ket
Step "Tinh kich thuoc tong"
$total = (Get-ChildItem $Dest -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
$totalGB = [math]::Round($total / 1GB, 2)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  XONG! Package tai: $Dest" -ForegroundColor Green
Write-Host ("  Tong kich thuoc : {0} GB" -f $totalGB) -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  HUONG DAN TREN MAY MOI (OFFLINE 100%):" -ForegroundColor Yellow
Write-Host "  1. Copy thu muc '$Dest' sang may moi"
Write-Host "  2. Cai dat: Python 3.10+, Node.js (tuy chon neu dung san EXE), FFmpeg"
Write-Host "  3. Chay: .\setup_offline.ps1  (De install package offline va link model)"
Write-Host "  4. Chay: .\run_native.ps1     (Se tu dong nap LLM va mo App)"
Write-Host ""
