# =============================================================================
# build_installer.ps1 -- Compress a staged bundle and compile the NSIS Setup.exe
#
#   .\build_installer.ps1 -Stage "D:\VD-Stage" [-Out "D:\VD-Installer"] [-Mx 1]
#
# Output: $Out\Setup.exe + $Out\app.7z  (ship BOTH, keep them together).
# Mx = 7z compression level (1 fastest .. 9 smallest). Default 1 -- most of the
# payload is incompressible model weights / torch DLLs, so 1 saves a lot of time.
# =============================================================================
param(
    [Parameter(Mandatory=$true)][string]$Stage,
    [string]$Out = "$env:USERPROFILE\Desktop\VideoDubbing-Installer",
    [int]$Mx = 1
)
$Src = $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function OK($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Die($m)  { Write-Host "  [XX] $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path "$Stage\Video Dubbing.exe")) { Die "Stage khong hop le (thieu Video Dubbing.exe): $Stage" }

# --- locate tools ---
$SevenZip = "$Src\node_modules\7zip-bin\win\x64\7za.exe"
if (-not (Test-Path $SevenZip)) { Die "Khong tim thay 7za.exe tai $SevenZip (chay 'npm install' o project root)." }
$MakeNsis = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache\nsis" -Recurse -Filter makensis.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
if (-not $MakeNsis) {
    $MakeNsis = (Get-Command makensis -ErrorAction SilentlyContinue).Source
}
if (-not $MakeNsis) { Die "Khong tim thay makensis.exe. Chay build-electron.ps1 mot lan (de electron-builder tai NSIS) hoac cai NSIS." }
OK "7za    : $SevenZip"
OK "makensis: $MakeNsis"

New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Payload = "$Out\app.7z"

# --- 1. compress the staged folder CONTENTS into app.7z ---
Step "Nen bundle -> app.7z (mx=$Mx) -- co the mat nhieu phut"
if (Test-Path $Payload) { Remove-Item $Payload -Force }
& $SevenZip a -t7z "-mx=$Mx" -ms=on -bsp1 $Payload "$Stage\*"
if ($LASTEXITCODE -ne 0) { Die "7za nen that bai (code $LASTEXITCODE)" }
$pSz = (Get-Item $Payload).Length
OK ("app.7z = {0:N2} GB" -f ($pSz/1GB))

# --- 2. compile Setup.exe (NSIS) ---
Step "Bien dich Setup.exe (NSIS)"
$BuildDir = Join-Path $env:TEMP ("vd_nsis_" + [System.IO.Path]::GetRandomFileName().Substring(0,6))
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
Copy-Item "$Src\installer\installer.nsi" "$BuildDir\installer.nsi" -Force
Copy-Item $SevenZip "$BuildDir\7za.exe" -Force
Push-Location $BuildDir
& $MakeNsis "installer.nsi"
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Die "makensis that bai (code $rc)" }
if (-not (Test-Path "$BuildDir\Setup.exe")) { Die "Khong sinh ra Setup.exe" }
Copy-Item "$BuildDir\Setup.exe" "$Out\Setup.exe" -Force
Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
OK ("Setup.exe = {0:N1} MB" -f ((Get-Item "$Out\Setup.exe").Length/1MB))

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  INSTALLER SAN SANG: $Out" -ForegroundColor Green
Write-Host "    Setup.exe  (chay cai dat)" -ForegroundColor Green
Write-Host "    app.7z     (du lieu -- de CUNG thu muc voi Setup.exe)" -ForegroundColor Green
Write-Host ""
Write-Host "  Tren may dich (co GPU NVIDIA): copy ca 2 file -> chay Setup.exe" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
