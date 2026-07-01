# =============================================================================
# pack_full_bundle.ps1 -- Stage a SELF-CONTAINED bundle for the NSIS installer.
# Produces a folder that runs on a clean Windows machine (no Python/Node/FFmpeg/
# Ollama pre-installed) with an NVIDIA GPU. Optimised for the CURRENT config.
#
#   .\pack_full_bundle.ps1 [-Stage "D:\VD-Stage"]
#
# Output: $Stage with Video Dubbing.exe + venv + python-runtime + models + ollama
#         + ffmpeg + source + frontend/dist + .env. NO offline_wheels (venv shipped).
# =============================================================================
param(
    [string]$Stage = "$env:USERPROFILE\Desktop\VideoDubbing-Stage"
)
$ErrorActionPreference = 'Stop'
$Src = $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function OK($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }

# robocopy mirror helper (treats robocopy's success exit codes 0-7 as OK)
function Mirror($from, $to, [string[]]$xd = @(), [string[]]$xf = @()) {
    $args = @($from, $to, '/MIR', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP')
    if ($xd.Count) { $args += '/XD'; $args += $xd }
    if ($xf.Count) { $args += '/XF'; $args += $xf }
    robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($from -> $to), code $LASTEXITCODE" }
}

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  Video Dubbing -- Stage Full Bundle" -ForegroundColor Magenta
Write-Host "  Src   : $Src"   -ForegroundColor Magenta
Write-Host "  Stage : $Stage" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta

New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# --- 1. App EXE (portable, with patched main.js) ---
Step "App EXE"
$exe = "$Src\dist-electron\Video Dubbing.exe"
if (-not (Test-Path $exe)) { $exe = "$Src\Video Dubbing.exe" }
if (-not (Test-Path $exe)) { throw "Video Dubbing.exe not found -- run build-electron.ps1 first." }
Copy-Item $exe "$Stage\Video Dubbing.exe" -Force
OK ("Video Dubbing.exe ({0:N1} MB)" -f ((Get-Item $exe).Length/1MB))

# --- 2. Frontend (prod EXE loads frontend/dist from disk) ---
Step "Frontend dist"
if (-not (Test-Path "$Src\frontend\dist\index.html")) { throw "frontend/dist missing -- run the frontend build." }
Mirror "$Src\frontend\dist" "$Stage\frontend\dist"
OK "frontend/dist"

# --- 3. Python source services ---
Step "Python services"
foreach ($svc in @('orchestrator','whisperx-service','tts-service','omnivoice-service')) {
    if (Test-Path "$Src\$svc") {
        Mirror "$Src\$svc" "$Stage\$svc" @('__pycache__','.pytest_cache') @('*.pyc','*.pyo')
        OK $svc
    }
}
if (Test-Path "$Src\GPT-SoVITS") {
    Mirror "$Src\GPT-SoVITS" "$Stage\GPT-SoVITS" @('__pycache__','.git') @('*.pyc','*.pyo')
    OK "GPT-SoVITS"
}

# --- 4. venv (cu118, ~11GB) -- shipped pre-built; pyvenv.cfg repaired at first launch ---
Step "venv (cu118 ~11GB -- may take minutes)"
Mirror "$Src\venv" "$Stage\venv" @('__pycache__')
OK "venv"

# --- 5. python-runtime (base Python 3.10.11 -- so venv works with no system Python) ---
Step "python-runtime (embedded Python 3.10.11)"
$base = ($env:PYTHON_RUNTIME_SRC) ; if (-not $base) { $base = "$env:LOCALAPPDATA\Programs\Python\Python310" }
if (-not (Test-Path "$base\python.exe")) { throw "Base Python 3.10 not found at $base. Set `$env:PYTHON_RUNTIME_SRC." }
Mirror $base "$Stage\python-runtime" @('__pycache__','Doc')
# pre-point pyvenv.cfg now (installer re-points it to the final install dir too)
$cfg = "$Stage\venv\pyvenv.cfg"
if (Test-Path $cfg) {
    (Get-Content $cfg) -replace '^home\s*=.*', "home = $Stage\python-runtime" | Set-Content $cfg -Encoding ASCII
}
OK "python-runtime"

# --- 6. FFmpeg (bin has ffmpeg.exe + ffprobe.exe) ---
Step "FFmpeg"
if (Test-Path "$Src\ffmpeg_extracted") {
    Mirror "$Src\ffmpeg_extracted" "$Stage\ffmpeg_extracted"
    OK "ffmpeg_extracted"
} else { Warn "ffmpeg_extracted missing -- ffprobe may be unavailable on target" }
if (Test-Path "$Src\ffmpeg.exe") { Copy-Item "$Src\ffmpeg.exe" "$Stage\ffmpeg.exe" -Force }

# --- 7. Ollama runtime (ollama.exe + lib/ CUDA) ---
Step "Ollama runtime"
$ollamaSrc = ($env:OLLAMA_SRC) ; if (-not $ollamaSrc) { $ollamaSrc = "$env:LOCALAPPDATA\Programs\Ollama" }
if (Test-Path "$ollamaSrc\ollama.exe") {
    Mirror $ollamaSrc "$Stage\ollama" @() @('ollama app.exe','unins000.dat','unins000.exe','unins000.msg','app.ico')
    OK "ollama (ollama.exe + lib/)"
} else { Warn "Ollama not found at $ollamaSrc -- translation will need a manual Ollama install" }

# --- 8. Models (skip empty dirs; ollama store carries the LLM weights) ---
Step "Models (~15GB -- may take minutes)"
foreach ($m in @('easyocr','whisper','omnivoice','ollama','huggingface')) {
    $mp = "$Src\models\$m"
    if (Test-Path $mp) {
        $sz = (Get-ChildItem $mp -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        if ($sz -gt 0) {
            Mirror $mp "$Stage\models\$m" @('__pycache__')
            OK ("models\$m ({0:N1} GB)" -f ($sz/1GB))
        }
    }
}

# --- 9. voices, config, icon, data dirs ---
Step "Config / voices / data"
if (Test-Path "$Src\voices") { Mirror "$Src\voices" "$Stage\voices" ; OK "voices" }
if (Test-Path "$Src\.env") { Copy-Item "$Src\.env" "$Stage\.env" -Force ; OK ".env (current tuned config)" }
elseif (Test-Path "$Src\orchestrator\.env.example") { Copy-Item "$Src\orchestrator\.env.example" "$Stage\.env" -Force ; OK ".env (from example)" }
if (Test-Path "$Src\icon.ico") { Copy-Item "$Src\icon.ico" "$Stage\icon.ico" -Force }
foreach ($d in @('data\input','data\output','data\temp')) { New-Item -ItemType Directory -Force -Path "$Stage\$d" | Out-Null }
OK "structure ready"

# --- 10. preflight + docs ---
Step "Preflight + tài liệu"
foreach ($f in @('preflight_check.ps1','Kiem-tra-he-thong.bat')) {
    if (Test-Path "$Src\$f") { Copy-Item "$Src\$f" "$Stage\$f" -Force; OK $f }
}
if (Test-Path "$Src\HUONG-DAN") { Mirror "$Src\HUONG-DAN" "$Stage\HUONG-DAN"; OK "HUONG-DAN" }

# --- Summary ---
$total = (Get-ChildItem $Stage -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host ("  STAGED: $Stage  ({0:N2} GB)" -f ($total/1GB)) -ForegroundColor Green
Write-Host "  Next:  .\build_installer.ps1 -Stage `"$Stage`"" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

# Reaching here means every step succeeded (failures throw under ErrorActionPreference='Stop').
# Force a clean exit code so callers can't misread robocopy's success code (1) as a failure.
exit 0
