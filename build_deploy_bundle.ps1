# =============================================================================
# build_deploy_bundle.ps1 -- ONE-COMMAND build of the deployable installer.
# Run this on the FULLY-PROVISIONED GPU/ML machine (the one with the cu118
# Python 3.10 venv + Ollama + all models). It:
#   0. Preflight: checks every prerequisite and ABORTS early with clear messages
#      (so you never start a ~30 GB copy only to fail at the last step).
#   1. build-electron.ps1   -> Video Dubbing.exe + frontend/dist
#   2. pack_full_bundle.ps1 -> self-contained staged folder
#   3. build_installer.ps1  -> Setup.exe + app.7z
#
#   .\build_deploy_bundle.ps1 [-Stage "D:\VD-Stage"] [-Out "D:\VD-Installer"] [-Mx 1] [-PreflightOnly] [-Force]
#
# Overrides (if Python 3.10 / Ollama live elsewhere):
#   $env:PYTHON_RUNTIME_SRC = "C:\path\to\Python310"
#   $env:OLLAMA_SRC         = "C:\path\to\Ollama"
# =============================================================================
param(
    [string]$Stage = "D:\VD-Stage",
    [string]$Out   = "D:\VD-Installer",
    [int]$Mx = 1,
    [switch]$PreflightOnly,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function OK($m)   { Write-Host "  [OK] $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m"   -ForegroundColor Yellow }
function Bad($m)  { Write-Host "  [XX] $m"   -ForegroundColor Red }

# ---- 0. Preflight: verify every prerequisite BEFORE the heavy steps ----------
Step "Preflight -- kiem tra tien de build"
$fail = 0

# node / npm
foreach ($t in 'node','npm') {
    if (Get-Command $t -ErrorAction SilentlyContinue) { OK "$t co tren PATH" }
    else { Bad "$t khong co tren PATH -- cai Node.js >= 18."; $fail++ }
}

# base Python 3.10 (becomes python-runtime/)
$py = if ($env:PYTHON_RUNTIME_SRC) { $env:PYTHON_RUNTIME_SRC } else { "$env:LOCALAPPDATA\Programs\Python\Python310" }
if (Test-Path "$py\python.exe") {
    $ver = (& "$py\python.exe" --version 2>&1)
    if ("$ver" -match '3\.10\.') { OK "Python 3.10 base: $py ($ver)" }
    else { Bad "Python o '$py' la '$ver' -- can 3.10.x. Set `$env:PYTHON_RUNTIME_SRC."; $fail++ }
} else { Bad "Khong tim thay Python 3.10 base tai '$py'. Cai Python 3.10 hoac set `$env:PYTHON_RUNTIME_SRC."; $fail++ }

# venv (the cu118 ML venv that gets shipped)
if (Test-Path "$Root\venv\Scripts\python.exe") {
    & "$Root\venv\Scripts\python.exe" -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('torch') and u.find_spec('whisperx') else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { OK "venv co torch + whisperx" }
    else { Bad "venv thieu torch/whisperx -- day khong phai venv ML cu118 day du. Chay setup_native.ps1 truoc."; $fail++ }
} else { Bad "Khong tim thay venv\Scripts\python.exe -- chay setup_native.ps1 truoc."; $fail++ }

# Ollama runtime
$ol = if ($env:OLLAMA_SRC) { $env:OLLAMA_SRC } else { "$env:LOCALAPPDATA\Programs\Ollama" }
if (Test-Path "$ol\ollama.exe") { OK "Ollama runtime: $ol" }
else { Warn "Khong tim thay ollama.exe tai '$ol' -- bundle se thieu LLM (dich hong tren may dich). Set `$env:OLLAMA_SRC." }

# ffmpeg_extracted (ffprobe)
$ffprobe = Get-ChildItem "$Root\ffmpeg_extracted" -Recurse -Filter ffprobe.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ffprobe) { OK "ffmpeg_extracted co ffprobe.exe" }
else { Warn "Khong tim thay ffmpeg_extracted\...\ffprobe.exe -- ffprobe se thieu tren may dich." }

# models
foreach ($m in @('whisper','omnivoice','ollama')) {
    $mp = "$Root\models\$m"
    $sz = if (Test-Path $mp) { (Get-ChildItem $mp -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } else { 0 }
    if ($sz -gt 100MB) { OK ("models\{0} ({1:N1} GB)" -f $m, ($sz/1GB)) }
    else { Bad "models\$m trong/thieu -- tai model truoc (setup_native.ps1)."; $fail++ }
}

# 7za (for build_installer)
if (Test-Path "$Root\node_modules\7zip-bin\win\x64\7za.exe") { OK "7za.exe co (node_modules)" }
else { Warn "Chua thay 7za.exe -- se can 'npm install' o project root truoc buoc installer." }

# disk free on Stage + Out drives
foreach ($pair in @(@($Stage,35),@($Out,20))) {
    $drv = (Split-Path $pair[0] -Qualifier).TrimEnd(':')
    try {
        $free = (Get-PSDrive $drv -ErrorAction Stop).Free
        if ($free -ge ($pair[1]*1GB)) { OK ("O {0}: {1:N0} GB trong (>= {2} GB)" -f $drv, ($free/1GB), $pair[1]) }
        else { Bad ("O {0}: chi {1:N0} GB trong -- can >= {2} GB." -f $drv, ($free/1GB), $pair[1]); $fail++ }
    } catch { Warn "Khong doc duoc dung luong o $drv (se tao khi build)." }
}

if ($fail -gt 0) {
    Write-Host "`n==> PREFLIGHT CHUA DAT: $fail loi. Khac phuc roi chay lai (xem [XX] o tren)." -ForegroundColor Red
    if (-not $Force) { exit 1 } else { Warn "-Force: tiep tuc du co loi." }
} else {
    Write-Host "`n==> PREFLIGHT DAT -- san sang build." -ForegroundColor Green
}
if ($PreflightOnly) { exit 0 }

# ---- 1..3 build chain --------------------------------------------------------
Step "1/3  build-electron.ps1  (rebuild Video Dubbing.exe + frontend/dist)"
& "$Root\build-electron.ps1"
if ($LASTEXITCODE -ne 0) { Bad "build-electron.ps1 that bai (code $LASTEXITCODE)"; exit 1 }

Step "2/3  pack_full_bundle.ps1 -Stage `"$Stage`"  (stage ~30 GB, may mat nhieu phut)"
& "$Root\pack_full_bundle.ps1" -Stage $Stage
if ($LASTEXITCODE -ne 0) { Bad "pack_full_bundle.ps1 that bai (code $LASTEXITCODE)"; exit 1 }

Step "3/3  build_installer.ps1 -Stage `"$Stage`" -Out `"$Out`" -Mx $Mx  (nen ~20 GB + NSIS)"
& "$Root\build_installer.ps1" -Stage $Stage -Out $Out -Mx $Mx
if ($LASTEXITCODE -ne 0) { Bad "build_installer.ps1 that bai (code $LASTEXITCODE)"; exit 1 }

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  HOAN TAT. Bo cai o: $Out" -ForegroundColor Green
Write-Host "    Setup.exe + app.7z  (ship CA HAI, de cung thu muc)" -ForegroundColor Green
Write-Host "  Kiem thu: copy 2 file sang may dich (co GPU NVIDIA) -> chay Setup.exe" -ForegroundColor Green
Write-Host "            -> 'Kiem tra he thong' -> 'Video Dubbing'." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
