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

# robocopy mirror helper: robocopy exit codes 0-7 mean success (bits: 1=copied, 2=extra),
# >=8 means at least one file/dir failed. Bare robocopy calls always "print OK" regardless, so a
# real failure would ship an incomplete transfer silently -- route every copy through this and
# throw (aborts under ErrorActionPreference='Stop') when robocopy signals a real failure.
function Mirror($from, $to, [string[]]$xd = @(), [string[]]$xf = @()) {
    $roboArgs = @($from, $to, '/MIR', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP')
    if ($xd.Count) { $roboArgs += '/XD'; $roboArgs += $xd }
    if ($xf.Count) { $roboArgs += '/XF'; $roboArgs += $xf }
    robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy that bai ($from -> $to), code $LASTEXITCODE" }
}

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
        Mirror "$Src\$svc" "$Dest\$svc" @('__pycache__', '.pytest_cache') @('*.pyc', '*.pyo')
        OK $svc
    }
}

# 2b. Frontend (cần cho setup_offline 'npm install' + frontend/dist mà EXE nạp). Bỏ node_modules.
Step "Chep Frontend"
if (Test-Path "$Src\frontend") {
    Mirror "$Src\frontend" "$Dest\frontend" @('node_modules')
    OK "frontend"
}

# 2c. GPT-SoVITS (code cho engine TTS thay thế gpt_sovits; bỏ qua nếu không dùng). Có thể rất lớn.
Step "Chep GPT-SoVITS (engine TTS thay thế, tùy chọn)"
if (Test-Path "$Src\GPT-SoVITS") {
    Mirror "$Src\GPT-SoVITS" "$Dest\GPT-SoVITS" @('__pycache__', '.git') @('*.pyc', '*.pyo')
    OK "GPT-SoVITS"
} else {
    Info "Khong co GPT-SoVITS (bo qua - dung omnivoice lam engine mac dinh)"
}

# 2d. Voices -- preset narrator-voice library (clip tham chieu clone theo quoc gia)
Step "Chep thu vien giong doc (voices)"
if (Test-Path "$Src\voices") {
    Mirror "$Src\voices" "$Dest\voices"
    OK "voices"
}

# 3. Models -- Ollama LLM la file lon nhat
Step "Chep Models Ollama - co the mat vai phut"
$ollamaLocal = "$env:USERPROFILE\.ollama\models"
if (Test-Path "$Src\models\ollama") {
    Mirror "$Src\models\ollama" "$Dest\models\ollama"
    $sz = (Get-ChildItem "$Src\models\ollama" -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\ollama  ({0:N1} GB)" -f ($sz/1GB))
} elseif (Test-Path $ollamaLocal) {
    Info "Dang chep model tu $ollamaLocal vao package..."
    # ~/.ollama/models IS the store (contains blobs/ + manifests/), and run_native.ps1 sets
    # OLLAMA_MODELS to ...\models\ollama\models, so copy one level deeper than the primary
    # branch (which mirrors the whole models\ollama tree that already includes the inner models\).
    Mirror $ollamaLocal "$Dest\models\ollama\models"
    $sz = (Get-ChildItem $ollamaLocal -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\ollama  ({0:N1} GB)" -f ($sz/1GB))
} else {
    Info "Khong co models\ollama"
}

Step "Chep Models HuggingFace (Whisper/TTS) - co the mat vai phut"
$hfLocal = "$env:USERPROFILE\.cache\huggingface\hub"
if (Test-Path "$Src\models\huggingface") {
    Mirror "$Src\models\huggingface" "$Dest\models\huggingface"
    $sz = (Get-ChildItem "$Src\models\huggingface" -Recurse -File | Measure-Object Length -Sum).Sum
    OK ("models\huggingface  ({0:N1} GB)" -f ($sz/1GB))
} elseif (Test-Path $hfLocal) {
    Info "Dang chep model tu $hfLocal vao package..."
    Mirror $hfLocal "$Dest\models\huggingface"
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
            Mirror $mp "$Dest\models\$m"
            OK ("models\$m  ({0:N0} MB)" -f ($sz/1MB))
        }
    }
}

# 4. Config & Scripts
Step "Chep Config, Scripts va Offline Wheels"
# hardware_check.ps1 is REQUIRED: setup_native.ps1 dot-sources it and hard-exits if missing.
# preflight_check.ps1 + Kiem-tra-he-thong.bat give the transfer target a system check too.
$files = @(".env", "icon.ico", "setup_native.ps1", "setup_offline.ps1",
           "hardware_check.ps1", "preflight_check.ps1", "Kiem-tra-he-thong.bat",
           "run_native.ps1", "pack_offline_bundle.ps1", "pack_transfer.ps1",
           "build-electron.ps1")
foreach ($f in $files) {
    if (Test-Path "$Src\$f") {
        Copy-Item "$Src\$f" "$Dest\$f" -Force
        OK $f
    }
}

if (Test-Path "$Src\offline_wheels") {
    Mirror "$Src\offline_wheels" "$Dest\offline_wheels"
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
