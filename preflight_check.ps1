param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Continue'
$results = New-Object System.Collections.ArrayList
function Add-Result($name, $status, $msg) { [void]$results.Add([pscustomobject]@{Name=$name;Status=$status;Msg=$msg}) }

# 1. OS
if ([Environment]::Is64BitOperatingSystem -and [Environment]::OSVersion.Version.Major -ge 10) {
    Add-Result "Hệ điều hành" "PASS" "Windows 64-bit"
} else { Add-Result "Hệ điều hành" "FAIL" "Cần Windows 10/11 64-bit" }

# 2. GPU + driver
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) { $smi = "$env:SystemRoot\System32\nvidia-smi.exe" }
if (-not $smi) {
    Add-Result "GPU NVIDIA" "FAIL" "Không tìm thấy nvidia-smi — máy chưa có GPU NVIDIA hoặc chưa cài driver."
} else {
    $line = (& $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if ($line) {
        $p = $line.Split(","); $name = $p[0].Trim(); $drv = $p[1].Trim(); $vram = [int]($p[2].Trim())
        Add-Result "GPU NVIDIA" "PASS" "$name (driver $drv)"
        if ([version]($drv) -lt [version]"452.39") { Add-Result "Driver GPU" "WARN" "Driver $drv có thể quá cũ cho CUDA 11.8 — nên cập nhật ≥ 452.39." }
        else { Add-Result "Driver GPU" "PASS" "driver $drv" }
        if ($vram -lt 16000) { Add-Result "VRAM" "FAIL" "$([math]::Round($vram/1024,1)) GB < 16 GB tối thiểu." }
        elseif ($vram -lt 24000) { Add-Result "VRAM" "PASS" "$([math]::Round($vram/1024,1)) GB — dùng VRAM_PROFILE=16gb." }
        else { Add-Result "VRAM" "PASS" "$([math]::Round($vram/1024,1)) GB — dùng VRAM_PROFILE=24gb." }
    } else { Add-Result "GPU NVIDIA" "FAIL" "nvidia-smi không trả dữ liệu." }
}

# 3. Disk
try {
    $drive = (Get-Item $Root).PSDrive.Name
    $free = (Get-PSDrive $drive).Free
    if ($free -ge 35GB) { Add-Result "Dung lượng đĩa" "PASS" ("{0:N0} GB trống trên ổ {1}:" -f ($free/1GB), $drive) }
    else { Add-Result "Dung lượng đĩa" "FAIL" ("Chỉ {0:N0} GB trống trên ổ {1}: — cần ≥ 35 GB." -f ($free/1GB), $drive) }
} catch { Add-Result "Dung lượng đĩa" "WARN" "Không đọc được dung lượng ổ đĩa." }

# 4. Ports
$listen = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort -Unique)
foreach ($port in 8000,8001,9880,3900,11434,5173) {
    if ($listen -contains $port) { Add-Result "Cổng $port" "WARN" "Đang bị chiếm — có thể xung đột khi chạy." }
    else { Add-Result "Cổng $port" "PASS" "trống" }
}

# 5. Bundle integrity (only when -Root points at an installed bundle)
$req = @("venv\Scripts\python.exe","python-runtime\python.exe","frontend\dist\index.html",".env",
         "ollama\ollama.exe","models\whisper","models\omnivoice","models\ollama\models\blobs","Video Dubbing.exe")
$hasBundle = Test-Path (Join-Path $Root "Video Dubbing.exe")
if ($hasBundle) {
    foreach ($rel in $req) {
        if (Test-Path (Join-Path $Root $rel)) { Add-Result "Bundle: $rel" "PASS" "có" }
        else { Add-Result "Bundle: $rel" "FAIL" "THIẾU — bundle chưa đầy đủ." }
    }
    $ffprobe = Get-ChildItem (Join-Path $Root "ffmpeg_extracted") -Recurse -Filter ffprobe.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ffprobe) { Add-Result "Bundle: ffprobe.exe" "PASS" "có" } else { Add-Result "Bundle: ffprobe.exe" "FAIL" "THIẾU ffprobe.exe" }
} else {
    Add-Result "Bundle" "WARN" "Chạy ngoài thư mục cài — bỏ qua kiểm tra toàn vẹn bundle."
}

# --- Report ---
$colors = @{PASS='Green';WARN='Yellow';FAIL='Red'}
Write-Host "`n==== KIỂM TRA HỆ THỐNG — VIDEO DUBBING ====`n" -ForegroundColor Cyan
foreach ($r in $results) {
    Write-Host ("[{0}] {1}: {2}" -f $r.Status, $r.Name, $r.Msg) -ForegroundColor $colors[$r.Status]
}
$fail = @($results | Where-Object { $_.Status -eq 'FAIL' }).Count
$warn = @($results | Where-Object { $_.Status -eq 'WARN' }).Count
Write-Host ""
if ($fail -eq 0) { Write-Host "==> SẴN SÀNG ($warn cảnh báo)." -ForegroundColor Green }
else { Write-Host "==> CHƯA ĐẠT: $fail lỗi cần khắc phục (xem [FAIL] ở trên)." -ForegroundColor Red }
$reportPath = Join-Path $PSScriptRoot "preflight_report.txt"
$results | ForEach-Object { "[{0}] {1}: {2}" -f $_.Status, $_.Name, $_.Msg } | Out-File $reportPath -Encoding utf8
Write-Host "Báo cáo đã lưu: $reportPath"
if ($fail -eq 0) { exit 0 } else { exit 1 }
