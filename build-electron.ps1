# =============================================================================
# build-electron.ps1 — Build Video Dubbing thành file EXE (Electron/Chromium)
# =============================================================================
# Output: dist-electron\Video Dubbing.exe  (portable, không cần cài đặt)
#         Sau đó copy về project root để chạy trực tiếp.
#
# Yêu cầu:
#   - Node.js >= 18  (node, npm trên PATH)
#   - venv/ đã tồn tại (chạy setup_native.ps1 trước)
#   - frontend/  có package.json và src/
# =============================================================================

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot

function Write-Step ($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-OK   ($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail ($msg) { Write-Host "  [!!] $msg" -ForegroundColor Red; exit 1 }

Set-Location $ProjectRoot

# ── Pre-flight checks ──────────────────────────────────────────────────────────

Write-Step "Kiểm tra công cụ cần thiết"

try { $nodeVer = (node --version 2>&1); Write-OK "Node.js $nodeVer" }
catch { Write-Fail "Không tìm thấy Node.js. Tải về từ https://nodejs.org/" }

try { $npmVer = (npm --version 2>&1); Write-OK "npm $npmVer" }
catch { Write-Fail "Không tìm thấy npm." }

if (-not (Test-Path "$ProjectRoot\venv\Scripts\python.exe")) {
    Write-Fail "Không tìm thấy venv. Chạy setup_native.ps1 trước!"
}
Write-OK "Python venv tồn tại"

# ── Step 1: Install root Electron dependencies ─────────────────────────────────

Write-Step "Bước 1/4 — Cài đặt Electron dependencies"
npm install --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { Write-Fail "npm install thất bại" }
Write-OK "Electron dependencies đã cài xong"

# ── Step 2: Install & build React frontend ─────────────────────────────────────

Write-Step "Bước 2/4 — Build React frontend"
Set-Location "$ProjectRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "  Cài đặt frontend dependencies..."
    npm install --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { Write-Fail "npm install (frontend) thất bại" }
}

npm run build
if ($LASTEXITCODE -ne 0) { Write-Fail "Vite build thất bại" }

Set-Location $ProjectRoot
Write-OK "frontend/dist/ đã được tạo"

# ── Step 3: Build Electron portable EXE ────────────────────────────────────────

Write-Step "Bước 3/4 — Build Electron EXE (portable)"
npx electron-builder --win portable --publish never
if ($LASTEXITCODE -ne 0) { Write-Fail "electron-builder thất bại" }
Write-OK "EXE đã build thành công"

# ── Step 4: Copy EXE to project root ──────────────────────────────────────────

Write-Step "Bước 4/4 — Copy EXE về project root"

$ExeSource = Get-ChildItem "$ProjectRoot\dist-electron\*.exe" -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notmatch 'Setup' } |
             Sort-Object LastWriteTime -Descending |
             Select-Object -First 1

if (-not $ExeSource) {
    Write-Fail "Không tìm thấy EXE trong dist-electron/"
}

$DestExe = "$ProjectRoot\VideoDubbing.exe"
Copy-Item $ExeSource.FullName $DestExe -Force
Write-OK "Đã copy: $($ExeSource.Name) → VideoDubbing.exe"

# ── Done ───────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host " BUILD THÀNH CÔNG!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host " File EXE: $DestExe" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host " Cách dùng:" -ForegroundColor Green
Write-Host "   1. Double-click VideoDubbing.exe" -ForegroundColor Green
Write-Host "   2. Chờ splash screen (30-90 giây lần đầu tải model)" -ForegroundColor Green
Write-Host "   3. Giao diện tự mở trong cửa sổ Chromium" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host " Lưu ý: venv/ và models/ phải nằm cùng thư mục với EXE" -ForegroundColor Yellow
Write-Host "=================================================================" -ForegroundColor Green
