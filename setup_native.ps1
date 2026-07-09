# =============================================================================
# Video Dubbing System — Native Online Installer (Không dùng Docker)
#
# Trình cài ONLINE: tự động kiểm tra phần cứng + tự tải mọi model/thành phần cần
# thiết trên máy đích (không cần bản bundle 20GB dựng sẵn).
#
# Ba việc chính:
#   1. Cổng kiểm tra phần cứng & thành phần bắt buộc — gộp TẤT CẢ lỗi rồi báo một
#      lần kèm cách khắc phục; lỗi NẶNG (không GPU NVIDIA, VRAM < 16GB, thiếu
#      Python/Node, thiếu đĩa...) sẽ CHẶN cài; lỗi nhẹ chỉ CẢNH BÁO rồi chạy tiếp.
#   2. Tự tải phụ thuộc (pip) + model (Whisper, OmniVoice, Ollama qwen2.5, ProPainter,
#      LatentSync, GPT-SoVITS, Demucs) + công cụ (FFmpeg, Ollama) nếu còn thiếu.
#   3. Mọi mục thiếu/không tương thích đều in rõ CÁCH KHẮC PHỤC.
# =============================================================================

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# Render Vietnamese (UTF-8) output correctly under Windows PowerShell 5.1, whose default console
# encoding garbles diacritics. (This file is saved with a UTF-8 BOM so its string literals parse
# correctly too.)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# Shared, tested hardware-check decision logic — thresholds (VRAM/driver/Python/disk) live in
# hardware_check.ps1 (one source of truth, covered by tests\test_hardware_check.ps1).
$hwCheck = Join-Path $ProjectRoot 'hardware_check.ps1'
if (-not (Test-Path $hwCheck)) { Write-Host "  [XX] Thiếu hardware_check.ps1 cạnh setup_native.ps1." -ForegroundColor Red; exit 1 }
. $hwCheck

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; exit 1 }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "  $msg" -ForegroundColor Gray }

# --- Offline detection (offline_wheels present = máy đích không có Internet) ---
$OfflineDir = "$ProjectRoot\offline_wheels"
$IsOffline = Test-Path $OfflineDir

# Download a URL to a file with retries. Downloads to a .part temp and atomically renames on
# success so an interrupted download never leaves a truncated file that a re-run would skip.
# $ProgressPreference is disabled during the transfer (Invoke-WebRequest is ~10x faster on PS 5.1
# without the progress bar). Returns $true on success.
function Get-File {
    param([string]$Url, [string]$OutFile, [int]$Retries = 3)
    if ((Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 0)) { return $true }
    $tmp = "$OutFile.part"
    $old = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        for ($i = 1; $i -le $Retries; $i++) {
            try {
                if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
                Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 1800
                if ((Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 0)) {
                    Move-Item -Force $tmp $OutFile
                    return $true
                }
            } catch {
                Write-Warn "Tải lỗi (lần $i/$Retries): $($_.Exception.Message)"
                Start-Sleep -Seconds ([math]::Min(30, 5 * $i))
            }
        }
    } finally {
        $ProgressPreference = $old
        if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
    }
    return $false
}

# Pull an Ollama model into $ModelsDir. Ollama's OLLAMA_MODELS is a SERVER-side setting, so a
# `pull` handled by a foreign server already on :11434 would land the blobs in ITS store, not ours
# (and the client env var would be ignored). To guarantee the model lands in $ModelsDir we ALWAYS
# start our own dedicated `ollama serve` on a private port with OLLAMA_MODELS=$ModelsDir and point
# the client at it via OLLAMA_HOST. Returns $true only after verifying blobs exist in $ModelsDir.
function Invoke-OllamaPull {
    param([string]$OllamaExe, [string]$Model, [string]$ModelsDir)
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
    $port = 11535  # private, avoids clashing with a foreign Ollama on the default 11434
    $env:OLLAMA_MODELS = $ModelsDir
    $env:OLLAMA_HOST = "127.0.0.1:$port"
    $serveProc = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru
    $up = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try { $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/api/tags" -TimeoutSec 2; $up = $true; break } catch {}
    }
    if ($up) { & $OllamaExe pull $Model }
    if ($serveProc) { try { Stop-Process -Id $serveProc.Id -Force -ErrorAction SilentlyContinue } catch {} }
    # Trust the on-disk result, not the exit code: confirm at least one blob landed in OUR store.
    $blobs = Join-Path $ModelsDir 'blobs'
    return ([bool]($up -and (Test-Path $blobs) -and (Get-ChildItem $blobs -File -ErrorAction SilentlyContinue | Select-Object -First 1)))
}

# =============================================================================
# 1. CỔNG KIỂM TRA PHẦN CỨNG & THÀNH PHẦN BẮT BUỘC (gộp tất cả, báo một lần)
#    Ngưỡng PHẢI khớp preflight_check.ps1 (VRAM 16GB, driver 452.39, đĩa 35GB) để
#    hai bộ kiểm tra không mâu thuẫn nhau.
# =============================================================================
Write-Step "Kiểm tra phần cứng & thành phần bắt buộc (Pre-flight)"

$checks = New-Object System.Collections.ArrayList
function Add-Check($name, $sev, $msg, $fix = '') { [void]$checks.Add([pscustomobject]@{ Name = $name; Sev = $sev; Msg = $msg; Fix = $fix }) }

# 1.1 OS
if ([Environment]::Is64BitOperatingSystem -and [Environment]::OSVersion.Version.Major -ge 10) {
    Add-Check "Hệ điều hành" "PASS" "Windows 64-bit"
} else {
    Add-Check "Hệ điều hành" "FAIL" "Cần Windows 10/11 64-bit." "Nâng cấp lên Windows 10/11 64-bit — hệ thống không hỗ trợ Windows cũ hơn hoặc bản 32-bit."
}

# 1.2 GPU + driver + VRAM
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) { $smi = "$env:SystemRoot\System32\nvidia-smi.exe" }
if (-not $smi) {
    Add-Check "GPU NVIDIA" "FAIL" "Không tìm thấy nvidia-smi — máy chưa có GPU NVIDIA hoặc chưa cài driver." "Cắm/kiểm tra GPU NVIDIA (bắt buộc, không hỗ trợ AMD/Intel) rồi cài driver mới nhất tại nvidia.com/drivers và khởi động lại máy."
} else {
    $line = (& $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if (-not $line) {
        Add-Check "GPU NVIDIA" "FAIL" "nvidia-smi không trả dữ liệu." "Cài lại/cập nhật driver NVIDIA mới nhất tại nvidia.com/drivers rồi thử lại."
    } else {
        $p = $line.Split(","); $gname = $p[0].Trim(); $drv = $p[1].Trim(); $vram = [int]($p[2].Trim())
        Add-Check "GPU NVIDIA" "PASS" "$gname (driver $drv)"
        switch ((Get-DriverSeverity $drv).Code) {
            'DRIVER_OLD'        { Add-Check "Driver GPU" "WARN" "Driver $drv có thể quá cũ cho CUDA 11.8 — nên cập nhật ≥ 452.39." "Tải driver mới tại nvidia.com/drivers cho đúng dòng GPU, cài rồi khởi động lại." }
            'DRIVER_OK'         { Add-Check "Driver GPU" "PASS" "driver $drv" }
            'DRIVER_UNREADABLE' { Add-Check "Driver GPU" "WARN" "Không đọc được phiên bản driver: $drv" }
        }
        $vgb = [math]::Round($vram / 1024, 1)
        switch ((Get-VramSeverity $vram).Code) {
            'VRAM_LOW'  { Add-Check "VRAM" "FAIL" "$vgb GB < 16 GB tối thiểu." "Cần GPU NVIDIA ≥ 16 GB VRAM (RTX 4080/3090/4090...). Đây là ngưỡng tối thiểu, không thể hạ." }
            'VRAM_16GB' { Add-Check "VRAM" "PASS" "$vgb GB — sẽ dùng VRAM_PROFILE=16gb." ; $vramProfile = '16gb' }
            'VRAM_24GB' { Add-Check "VRAM" "PASS" "$vgb GB — sẽ dùng VRAM_PROFILE=24gb." ; $vramProfile = '24gb' }
        }
    }
}

# 1.3 Disk (cần 35 GB cho bản cài online: model + venv + runtime)
try {
    $drvName = (Get-Item $ProjectRoot).PSDrive.Name
    $free = (Get-PSDrive $drvName).Free
    $freeGb = $free / 1GB
    if ((Get-DiskSeverity $freeGb).Severity -eq 'PASS') {
        Add-Check "Dung lượng đĩa" "PASS" ("{0:N0} GB trống trên ổ {1}:" -f $freeGb, $drvName)
    } else {
        Add-Check "Dung lượng đĩa" "FAIL" ("Chỉ {0:N0} GB trống trên ổ {1}: — cần ≥ 35 GB." -f $freeGb, $drvName) "Giải phóng dung lượng (xóa file rác, chuyển bớt dữ liệu) hoặc đặt dự án trên ổ đĩa khác còn ≥ 35 GB."
    }
} catch { Add-Check "Dung lượng đĩa" "WARN" "Không đọc được dung lượng ổ đĩa." }

# 1.4 Python 3.10 (venv ABI). torch CUDA 11.8 có wheel cho 3.10–3.12; 3.13+ chưa có.
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Add-Check "Python 3.10" "FAIL" "Không tìm thấy Python." "Cài Python 3.10.x (khuyến nghị 3.10.11) tại python.org/downloads/release/python-31011/ — nhớ tích 'Add python.exe to PATH', sau đó MỞ LẠI cửa sổ và chạy lại."
} else {
    $pyVer = (& python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null)
    switch ((Get-PythonSeverity $pyVer).Code) {
        'PY_UNREADABLE' { Add-Check "Python 3.10" "WARN" "Không đọc được phiên bản Python." }
        'PY_OLD'        { Add-Check "Python 3.10" "FAIL" "Python $pyVer quá cũ (cần ≥ 3.10)." "Cài Python 3.10.x tại python.org (tích Add to PATH) rồi mở lại cửa sổ." }
        'PY_NEW'        { Add-Check "Python 3.10" "FAIL" "Python $pyVer chưa có bản PyTorch CUDA 11.8." "Cài thêm Python 3.10.x tại python.org và dùng bản đó (đặt biến PYTHON_EXE trỏ tới python.exe 3.10, hoặc để 3.10 lên đầu PATH)." }
        'PY_NOTREC'     { Add-Check "Python 3.10" "WARN" "Python $pyVer — khuyến nghị dùng 3.10.x (bản đã kiểm thử)." "Nếu gặp lỗi khi cài torch/whisperx, hãy cài Python 3.10.x." }
        'PY_OK'         { Add-Check "Python 3.10" "PASS" "Python $pyVer" }
    }
}

# 1.5 Node.js (cần cho giao diện web)
if (Get-Command node -ErrorAction SilentlyContinue) {
    Add-Check "Node.js" "PASS" "đã có"
} else {
    Add-Check "Node.js" "FAIL" "Không tìm thấy Node.js." "Cài Node.js LTS (bản Windows 64-bit) tại nodejs.org rồi mở lại cửa sổ."
}

# 1.6 Git (chỉ cần cho tính năng TUỲ CHỌN ProPainter/LatentSync → chỉ cảnh báo)
if (Get-Command git -ErrorAction SilentlyContinue) {
    Add-Check "Git" "PASS" "đã có"
} else {
    Add-Check "Git" "WARN" "Không có Git — sẽ bỏ qua tải ProPainter/LatentSync (tính năng tuỳ chọn)." "Cài Git tại git-scm.com nếu cần lip-sync (LatentSync) hoặc xoá phụ đề gốc (ProPainter)."
}

# 1.7 FFmpeg (tự tải ở bước sau nếu thiếu → chỉ cảnh báo; offline thì bắt buộc có sẵn)
$ffbin = "$ProjectRoot\ffmpeg_extracted\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -or (Test-Path $ffbin)) {
    Add-Check "FFmpeg" "PASS" "đã có"
} elseif ($IsOffline) {
    Add-Check "FFmpeg" "FAIL" "Thiếu FFmpeg (đang ở chế độ offline, không thể tải)." "Chép sẵn thư mục ffmpeg_extracted vào dự án, hoặc cài FFmpeg và thêm vào PATH."
} else {
    Add-Check "FFmpeg" "WARN" "Chưa có — sẽ tự tải bản portable ở bước sau." ""
}

# --- Báo cáo & chặn nếu có lỗi nặng ---
$col = @{ PASS = 'Green'; WARN = 'Yellow'; FAIL = 'Red' }
Write-Host ""
foreach ($c in $checks) {
    Write-Host ("  [{0}] {1}: {2}" -f $c.Sev, $c.Name, $c.Msg) -ForegroundColor $col[$c.Sev]
    if ($c.Sev -ne 'PASS' -and $c.Fix) { Write-Host ("        -> Khắc phục: {0}" -f $c.Fix) -ForegroundColor DarkYellow }
}
$fails = @($checks | Where-Object { $_.Sev -eq 'FAIL' })
$warns = @($checks | Where-Object { $_.Sev -eq 'WARN' })
Write-Host ""
if ((Get-GateDecision @($checks | ForEach-Object { $_.Sev })) -eq 'STOP') {
    Write-Host ("==> CHƯA THỂ CÀI: {0} lỗi nặng cần khắc phục trước (xem [XX]/[FAIL] ở trên)." -f $fails.Count) -ForegroundColor Red
    Write-Host "    Sau khi khắc phục xong, chạy lại: .\setup_native.ps1" -ForegroundColor Red
    exit 1
}
Write-OK ("Phần cứng & thành phần đạt yêu cầu ($($warns.Count) cảnh báo). Bắt đầu cài đặt...")

# =============================================================================
# 2. FFmpeg — tự tải bản portable nếu thiếu (không chặn cài)
# =============================================================================
if (-not ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -or (Test-Path $ffbin)) -and -not $IsOffline) {
    Write-Step "Tải FFmpeg (portable, ~100MB)"
    $ffzip = "$ProjectRoot\ffmpeg.zip"
    if (Get-File "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $ffzip) {
        try {
            Expand-Archive -Path $ffzip -DestinationPath "$ProjectRoot\ffmpeg_extracted" -Force
            if (Test-Path $ffbin) { Write-OK "Đã tải & giải nén FFmpeg." }
            else { Write-Warn "Giải nén FFmpeg xong nhưng không thấy ffmpeg.exe ở đường dẫn mong đợi." }
        } catch { Write-Warn "Giải nén FFmpeg thất bại: $($_.Exception.Message)" }
        Remove-Item $ffzip -Force -ErrorAction SilentlyContinue
    } else {
        Write-Warn "Tải FFmpeg thất bại. Cài thủ công tại gyan.dev/ffmpeg/builds rồi thêm vào PATH."
    }
}

# =============================================================================
# 3. Thiết lập Môi trường Python (venv)
# =============================================================================
Write-Step "Thiết lập Python Virtual Environment"

if (-not (Test-Path "$ProjectRoot\venv")) {
    Write-Host "Đang tạo venv mới..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Tạo venv thất bại." }
}
Write-OK "Venv đã sẵn sàng tại .\venv"

$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"
$PipExe = "$ProjectRoot\venv\Scripts\pip.exe"

if ($IsOffline) {
    Write-Host "Phát hiện thư mục offline_wheels, kích hoạt chế độ Cài đặt Offline (Siêu tốc)..." -ForegroundColor Yellow
    $PipArgs = @('--no-index', "--find-links=$OfflineDir")
} else {
    $PipArgs = @()
}

# Cập nhật pip
& $PythonExe -m pip install @PipArgs --upgrade pip

# 3.1 Cài đặt PyTorch với CUDA (mặc định cu118 để tương thích WhisperX)
Write-Step "Cài đặt PyTorch (CUDA 11.8)"
if ($IsOffline) {
    & $PipExe install @PipArgs torch torchvision torchaudio
} else {
    & $PipExe install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
}
if ($LASTEXITCODE -ne 0) { Write-Fail "Cài đặt PyTorch thất bại." }

# OCR text-detection backend = EasyOCR (CRAFT, pure PyTorch on GPU) — installed via
# orchestrator/requirements.txt. No paddlepaddle needed (it required the broken cuDNN 8).

# 3.2 Cài đặt các thư viện hệ thống
Write-Step "Cài đặt Backend Dependencies"

# Orchestrator
& $PipExe install @PipArgs -r "$ProjectRoot\orchestrator\requirements.txt"
# WhisperX framework deps + engine (git HEAD online; bundled sdist offline)
& $PipExe install @PipArgs -r "$ProjectRoot\whisperx-service\requirements.txt"
if ($IsOffline) {
    & $PipExe install @PipArgs --pre whisperx
} else {
    & $PipExe install git+https://github.com/m-bain/whisperx.git
}
# TTS (GPT-SoVITS adapter)
& $PipExe install @PipArgs -r "$ProjectRoot\tts-service\requirements.txt"
# OmniVoice (engine TTS mặc định)
& $PipExe install @PipArgs -r "$ProjectRoot\omnivoice-service\requirements.txt"

# Cài đặt Demucs cục bộ để hỗ trợ native
& $PipExe install @PipArgs demucs

# Cài đặt vLLM (Tuỳ chọn)
Write-Step "Cài đặt vLLM (Tuỳ chọn - Thay thế Ollama)"
Write-Host "Lưu ý: Trên Windows Native, cài đặt vLLM có thể gặp lỗi (đặc biệt liên quan đến flash-attn). Hệ thống sẽ tự dùng Ollama nếu vLLM không khả dụng." -ForegroundColor Yellow
& $PipExe install @PipArgs vllm
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Không thể cài đặt vLLM. Hãy đảm bảo dùng Ollama làm LLM_BACKEND."
} else {
    Write-OK "Đã cài đặt vLLM thành công."
}

# Cài đặt thư viện cho ProPainter (Tuỳ chọn)
Write-Step "Cài đặt phụ thuộc cho ProPainter"
& $PipExe install @PipArgs einops scipy openmim
Write-Host "Đang cài đặt mmcv..."
if ($IsOffline) {
    & $PipExe install @PipArgs "mmcv>=2.0.0"
} else {
    & $PythonExe -m mim install "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html
}
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Cài đặt mmcv thất bại. Tính năng ProPainter có thể không hoạt động."
}

# =============================================================================
# 4. Khởi tạo thư mục và tải model
# =============================================================================
Write-Step "Tạo thư mục models và cấu hình"
$dirs = @("models\ollama", "models\whisper", "models\demucs", "models\tts", "models\propainter", "models\omnivoice", "data\input", "data\output", "data\temp")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path "$ProjectRoot\$d" | Out-Null
}

# 4.1 ProPainter (git clone chỉ khi có Git; nếu không có thì bỏ qua tính năng tuỳ chọn)
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if (-not (Test-Path "$ProjectRoot\models\propainter\inference_propainter.py")) {
    if ($hasGit -and -not $IsOffline) {
        Write-Host "Đang tải mã nguồn ProPainter..."
        git clone https://github.com/sczhou/ProPainter.git "$ProjectRoot\models\propainter"
    } else {
        Write-Warn "Bỏ qua ProPainter (cần Git + mạng). Tính năng xoá phụ đề gốc sẽ không dùng được cho tới khi tải thủ công."
    }
}

if (Test-Path "$ProjectRoot\models\propainter\inference_propainter.py") {
    Write-Host "Kích hoạt tải trọng số ProPainter (Khoảng 2GB)..."
    $propainter_script = @"
import os
import sys
import urllib.request

def dl(url, path):
    # Skip only if a non-empty file already exists. Download to a .part temp and atomically
    # replace on success so an interrupted download never leaves a truncated file behind that
    # future runs would blindly skip. Raise on failure so the caller can surface it.
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    tmp = path + '.part'
    print(f'Downloading {os.path.basename(path)}...')
    try:
        urllib.request.urlretrieve(url, tmp)
        if os.path.getsize(tmp) == 0:
            raise IOError('file rỗng sau khi tải')
        os.replace(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f'Lỗi khi tải {os.path.basename(path)}: {e}', file=sys.stderr)
        raise

weights_dir = os.path.join(r'$ProjectRoot', 'models', 'propainter', 'weights')
os.makedirs(weights_dir, exist_ok=True)

# The three nets inference_propainter.py actually loads: RAFT, RecurrentFlowComplete, ProPainter.
# (i3d_rgb_imagenet.pt is only for VFID eval metrics, not inference — do NOT ship it.)
downloads = [
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/ProPainter.pth', os.path.join(weights_dir, 'ProPainter.pth')),
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/raft-things.pth', os.path.join(weights_dir, 'raft-things.pth')),
    ('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/recurrent_flow_completion.pth', os.path.join(weights_dir, 'recurrent_flow_completion.pth')),
]
failed = False
for url, path in downloads:
    try:
        dl(url, path)
    except Exception:
        failed = True
if failed:
    sys.exit(1)
"@
    & $PythonExe -c $propainter_script
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Tải một số trọng số ProPainter thất bại. ProPainter có thể không hoạt động; hãy chạy lại setup để thử lại."
    } else {
        Write-OK "Đã kiểm tra weights ProPainter."
    }
}

# 4.2 LatentSync (lip-sync, tuỳ chọn)
if (-not (Test-Path "$ProjectRoot\models\latentsync\scripts\inference.py")) {
    if ($hasGit -and -not $IsOffline) {
        Write-Host "Đang tải mã nguồn LatentSync (Lip-Sync)..."
        git clone https://github.com/bytedance/LatentSync.git "$ProjectRoot\models\latentsync"
        # Cài đặt dependencies của LatentSync
        & $PipExe install @PipArgs -r "$ProjectRoot\models\latentsync\requirements.txt"
        & $PipExe install @PipArgs huggingface_hub diffusers
    } else {
        Write-Warn "Bỏ qua LatentSync (cần Git + mạng). Tính năng lip-sync sẽ không dùng được cho tới khi tải thủ công."
    }
} else {
    Write-OK "Phát hiện mã nguồn LatentSync đã có sẵn (Offline/Cache), bỏ qua git clone."
}

if (Test-Path "$ProjectRoot\models\latentsync\scripts\inference.py") {
    Write-Host "Kích hoạt tải trọng số LatentSync (có thể mất thời gian do file lớn)..."
    $hf_script = @"
import os
from huggingface_hub import snapshot_download
target_dir = os.path.join(r'$ProjectRoot', 'models', 'latentsync', 'checkpoints')
os.makedirs(target_dir, exist_ok=True)
if not os.path.exists(os.path.join(target_dir, 'latentsync_unet.pt')):
    print('Downloading LatentSync weights from huggingface...')
    snapshot_download(repo_id='ByteDance/LatentSync', local_dir=target_dir)
"@
    & $PythonExe -c $hf_script
    Write-OK "Đã kiểm tra weights LatentSync."
}

# --- MuseTalk (engine lip-sync nhanh, TUỲ CHỌN) ---
# ⚠️ CHƯA TEST TRÊN GPU — verify trước khi dùng. Chỉ tải khi LIPSYNC_ENGINE=musetalk để không
# phình setup mặc định. Repo + danh sách weights (whisper/dwpose/sd-vae/musetalk) tuỳ version —
# chỉnh repo_id/đường dẫn nếu tải lỗi.
if ($env:LIPSYNC_ENGINE -eq "musetalk" -and $hasGit -and -not $IsOffline) {
    if (-not (Test-Path "$ProjectRoot\models\musetalk\scripts\inference.py")) {
        Write-Host "Đang tải mã nguồn MuseTalk (Lip-Sync nhanh)..."
        git clone https://github.com/TMElyralab/MuseTalk.git "$ProjectRoot\models\musetalk"
        & $PipExe install @PipArgs -r "$ProjectRoot\models\musetalk\requirements.txt"
    } else {
        Write-OK "Phát hiện mã nguồn MuseTalk đã có sẵn, bỏ qua git clone."
    }
    Write-Host "Kích hoạt tải trọng số MuseTalk..."
    $mt_script = @"
import os
from huggingface_hub import snapshot_download
target_dir = os.path.join(r'$ProjectRoot', 'models', 'musetalk', 'models')
os.makedirs(target_dir, exist_ok=True)
print('Downloading MuseTalk weights from huggingface...')  # verify repo_id + layout theo version
snapshot_download(repo_id='TMElyralab/MuseTalk', local_dir=target_dir)
"@
    & $PythonExe -c $mt_script
    Write-OK "Đã kiểm tra weights MuseTalk (CHƯA TEST)."
}

# --- BS-Roformer (tách nhạc SOTA, TUỲ CHỌN) ---
# ⚠️ CHƯA TEST TRÊN GPU — verify trước khi dùng. Chỉ cài khi SEPARATION_ENGINE=bs_roformer. Gói
# audio-separator tự tải model .ckpt lần đầu chạy (cần mạng lần đó) — hoặc pre-download vào cache
# của nó để chạy offline hoàn toàn.
if ($env:SEPARATION_ENGINE -eq "bs_roformer") {
    Write-Host "Đang cài audio-separator (BS-Roformer)..."
    & $PipExe install @PipArgs "audio-separator[gpu]"
    Write-OK "Đã cài audio-separator (CHƯA TEST). Model tải lần đầu chạy hoặc pre-download thủ công."
}

# --- WSOLA time-stretch (tuỳ chọn) ---
if ($env:TIMESTRETCH_ALGO -eq "wsola") {
    Write-Host "Đang cài audiotsm (WSOLA time-stretch)..."
    & $PipExe install @PipArgs audiotsm
    Write-OK "Đã cài audiotsm."
}

# 4.3 Demucs (tách nhạc/giọng, engine mặc định)
Write-Step "Tải trước mô hình Demucs (htdemucs_ft)"
if ($IsOffline) {
    Write-Warn "Đang ở chế độ offline — bỏ qua tải Demucs. Model cần có sẵn trong cache torch hub."
} else {
    Write-Host "Kích hoạt tải trước mô hình htdemucs_ft..."
    & $PythonExe -c "from demucs.pretrained import get_model; get_model('htdemucs_ft')"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Chưa tải được htdemucs_ft. Model sẽ tự tải khi chạy lần đầu (cần mạng lúc đó)."
    } else {
        Write-OK "Đã tải htdemucs_ft."
    }
}

# 4.4 WhisperX (nhận diện giọng nói) — mặc định large-v3-turbo để khớp .env.example
Write-Step "Tải trước mô hình WhisperX (large-v3-turbo, ~1.5GB)"
$whisperModel = if ($env:WHISPER_MODEL) { $env:WHISPER_MODEL } else { "large-v3-turbo" }
$whisper_dl_script = @"
import os, sys
model_name = r'$whisperModel'
model_dir  = os.path.join(r'$ProjectRoot', 'models', 'whisper')
os.makedirs(model_dir, exist_ok=True)
print(f'Downloading WhisperX model [{model_name}] to {model_dir} ...')
try:
    import whisperx
    m = whisperx.load_model(model_name, 'cpu', compute_type='int8', download_root=model_dir)
    del m
    print('WhisperX model ready.')
except Exception as e:
    print(f'Canh bao: Khong the tai WhisperX model: {e}', file=sys.stderr)
    print('Model se duoc tai tu dong lan dau su dung.', file=sys.stderr)
    sys.exit(1)
"@
& $PythonExe -c $whisper_dl_script
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Không thể tải trước WhisperX model. Model sẽ tự tải khi sử dụng lần đầu."
} else {
    Write-OK "Đã tải WhisperX model."
}

# 4.5 OmniVoice (engine TTS mặc định) — tải trọng số HF k2-fsa/OmniVoice vào models\omnivoice
Write-Step "Tải model OmniVoice (engine TTS mặc định)"
if ($IsOffline) {
    Write-Warn "Đang ở chế độ offline — bỏ qua tải OmniVoice. Cần chép sẵn thư mục models\omnivoice."
} else {
    $omni_script = @"
import os, sys
target = os.path.join(r'$ProjectRoot', 'models', 'omnivoice')
os.makedirs(target, exist_ok=True)
# Gate on a COMPLETE marker, not mere non-emptiness: an interrupted snapshot_download leaves the
# dir non-empty but partial, which both this script and omnivoice-service would wrongly treat as
# ready. snapshot_download is resumable, so re-running when the marker is absent is safe.
marker = os.path.join(target, '.download_complete')
if os.path.exists(marker):
    print('OmniVoice model already present.'); sys.exit(0)
try:
    from huggingface_hub import snapshot_download
    print('Downloading OmniVoice (k2-fsa/OmniVoice) from huggingface...')
    snapshot_download(repo_id='k2-fsa/OmniVoice', local_dir=target)
    open(marker, 'w').close()
    print('OmniVoice model ready.')
except Exception as e:
    print(f'Canh bao: khong tai duoc OmniVoice: {e}', file=sys.stderr)
    sys.exit(1)
"@
    & $PythonExe -c $omni_script
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Chưa tải được model OmniVoice. Dịch vụ TTS sẽ tự tải ở lần chạy đầu (cần mạng lúc đó)."
    } else {
        Write-OK "Đã tải model OmniVoice."
    }
}

# 4.6 GPT-SoVITS pretrained (engine TTS thay thế). The old single pretrained_models.zip now 404s;
# the HF repo lj1995/GPT-SoVITS ships individual folders (chinese-roberta-wwm-ext-large,
# chinese-hubert-base, ...). snapshot_download straight into GPT_SoVITS\pretrained_models so the
# layout matches tts-service's expected path. Gate on a completion marker for safe re-runs.
Write-Step "Kiểm tra và tải GPT-SoVITS Pretrained Models"
$gptSoVitsPretrainedDir = "$ProjectRoot\GPT-SoVITS\GPT_SoVITS\pretrained_models"
if (Test-Path "$gptSoVitsPretrainedDir\.download_complete") {
    Write-OK "GPT-SoVITS Pretrained Models đã tồn tại."
} elseif ($IsOffline) {
    Write-Warn "Offline — bỏ qua tải GPT-SoVITS. Cần chép sẵn GPT-SoVITS\GPT_SoVITS\pretrained_models nếu dùng engine này."
} else {
    Write-Host "Đang tải GPT-SoVITS Pretrained Models (sẽ tốn thời gian)..." -ForegroundColor Yellow
    $gpt_script = @"
import os, sys
target = os.path.join(r'$ProjectRoot', 'GPT-SoVITS', 'GPT_SoVITS', 'pretrained_models')
os.makedirs(target, exist_ok=True)
marker = os.path.join(target, '.download_complete')
try:
    from huggingface_hub import snapshot_download
    print('Downloading GPT-SoVITS pretrained (lj1995/GPT-SoVITS) from huggingface...')
    snapshot_download(repo_id='lj1995/GPT-SoVITS', local_dir=target)
    open(marker, 'w').close()
    print('GPT-SoVITS pretrained ready.')
except Exception as e:
    print(f'Loi khi tai GPT-SoVITS pretrained: {e}', file=sys.stderr)
    sys.exit(1)
"@
    & $PythonExe -c $gpt_script
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Không thể tải GPT-SoVITS Pretrained Models. TTS (GPT-SoVITS) có thể không hoạt động."
    } else {
        Write-OK "Đã tải GPT-SoVITS Pretrained Models."
    }
}

# 4.7 Ollama (LLM backend mặc định để dịch) — tự tải binary + pull model qwen2.5:14b
Write-Step "Cài đặt Ollama & tải model dịch (LLM)"
$ollamaExe = $null
$bundledOllama = "$ProjectRoot\ollama\ollama.exe"
if (Test-Path $bundledOllama) {
    $ollamaExe = $bundledOllama
} elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
} elseif (-not $IsOffline) {
    Write-Host "Đang tải Ollama (standalone, ~700MB)..."
    $olzip = "$ProjectRoot\ollama-windows-amd64.zip"
    if (Get-File "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip" $olzip) {
        try {
            Expand-Archive -Path $olzip -DestinationPath "$ProjectRoot\ollama" -Force
            if (Test-Path $bundledOllama) { $ollamaExe = $bundledOllama; Write-OK "Đã cài Ollama vào .\ollama" }
        } catch { Write-Warn "Giải nén Ollama thất bại: $($_.Exception.Message)" }
        Remove-Item $olzip -Force -ErrorAction SilentlyContinue
    } else {
        Write-Warn "Tải Ollama thất bại."
    }
}

$llmModel = if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "qwen2.5:14b" }
if (-not $ollamaExe) {
    Write-Warn "Chưa có Ollama. Tải thủ công tại ollama.com/download/OllamaSetup.exe, rồi chạy: ollama pull $llmModel"
} elseif ($IsOffline) {
    Write-Warn "Offline — bỏ qua tải model LLM. Cần chép sẵn models\ollama\models hoặc pull khi có mạng: ollama pull $llmModel"
} else {
    Write-Host "Đang tải model dịch '$llmModel' (khoảng 9GB, tốn thời gian)..."
    if (Invoke-OllamaPull $ollamaExe $llmModel "$ProjectRoot\models\ollama\models") {
        Write-OK "Đã tải model LLM $llmModel."
    } else {
        Write-Warn "Chưa tải được model LLM $llmModel. Chạy thủ công sau: `$env:OLLAMA_MODELS='$ProjectRoot\models\ollama\models'; & '$ollamaExe' pull $llmModel"
    }
}

# 4.8 .env — create from example and persist the VRAM profile the gate actually detected, so a
# 16 GB card runs with VRAM_PROFILE=16gb instead of the example's default 24gb (the gate prints
# the profile; without this it would not be honored at runtime). Written UTF-8 without BOM so the
# .env parser (and the Vietnamese comments) stay intact.
$envPath = "$ProjectRoot\.env"
if (-not (Test-Path $envPath)) {
    Copy-Item "$ProjectRoot\orchestrator\.env.example" $envPath
    if ($vramProfile) {
        $envTxt = [System.IO.File]::ReadAllText($envPath, [System.Text.Encoding]::UTF8)
        $envTxt = $envTxt -replace '(?m)^VRAM_PROFILE=.*', "VRAM_PROFILE=$vramProfile"
        [System.IO.File]::WriteAllText($envPath, $envTxt, (New-Object System.Text.UTF8Encoding($false)))
        Write-OK "Đã tạo .env (VRAM_PROFILE=$vramProfile)."
    } else {
        Write-OK "Đã tạo .env từ mẫu."
    }
}

# =============================================================================
# 5. Cài đặt Frontend
# =============================================================================
Write-Step "Cài đặt Frontend Dependencies"
Set-Location "$ProjectRoot\frontend"
npm install
if ($LASTEXITCODE -ne 0) { Write-Fail "Lỗi khi chạy npm install." }
Set-Location $ProjectRoot

Write-Step "SETUP HOÀN TẤT!"
Write-Host "Đã tự động: kiểm tra phần cứng, cài phụ thuộc, tải model (Whisper/OmniVoice/Ollama/Demucs...)." -ForegroundColor Green
if ($warns.Count -gt 0) {
    Write-Host "Có $($warns.Count) cảnh báo ở phần kiểm tra đầu — xem lại nếu gặp lỗi khi chạy." -ForegroundColor Yellow
}
Write-Host "Chạy .\run_native.ps1 để khởi động hệ thống." -ForegroundColor Green
