# =============================================================================
# Video Dubbing System — Native Run
# Khởi động toàn bộ hệ thống bằng PowerShell (thay thế docker-compose up)
# =============================================================================

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# The runtime interpreter MUST match the venv's Python minor version — venv\Lib\site-packages
# holds cp3XX binary extensions (av, torch, ctranslate2) that ABI-lock to it. Prefer a matching
# SYSTEM python (dodges a shm.dll loader bug in venv's own python.exe); else use venv python.
# Override with $env:PYTHON_EXE. NOTE: do NOT trust `python` on PATH blindly — a stray 3.11/3.14
# there would load against cp310 site-packages and crash on import.
$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"
$PyVer = "3.10"
$VenvCfg = "$ProjectRoot\venv\pyvenv.cfg"
if (Test-Path $VenvCfg) {
    $cfgMatch = Select-String -Path $VenvCfg -Pattern 'version\s*=\s*(\d+\.\d+)' | Select-Object -First 1
    if ($cfgMatch) { $PyVer = $cfgMatch.Matches[0].Groups[1].Value }
}
$NoDot = $PyVer.Replace(".", "")
$Cands = @()
if ($env:PYTHON_EXE) { $Cands += $env:PYTHON_EXE }
$Cands += "$env:LOCALAPPDATA\Programs\Python\Python$NoDot\python.exe"
$Cands += "C:\Python$NoDot\python.exe"
$gcPy = Get-Command python -ErrorAction SilentlyContinue
if ($gcPy) { $Cands += $gcPy.Source }
foreach ($c in $Cands) {
    if ($c -and (Test-Path $c) -and ($c -notlike "*\venv\*")) {
        $vshown = (& $c --version)
        if ($vshown -match ("Python " + [regex]::Escape($PyVer) + "\.")) { $PythonExe = $c; break }
    }
}

if (-not (Test-Path "$ProjectRoot\venv")) {
    Write-Host "[XX] Không tìm thấy venv. Vui lòng chạy setup_native.ps1 trước." -ForegroundColor Red
    exit 1
}

Write-Host "Khởi động các dịch vụ (các cửa sổ phụ sẽ được mở)..." -ForegroundColor Cyan

# Nạp file .env (nếu có)
if (Test-Path "$ProjectRoot\.env") {
    Get-Content "$ProjectRoot\.env" | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)\s*=\s*(.*)') {
            $name = $matches[1].Trim()
            $val = $matches[2].Trim()
            if ($val -match '^"(.*)"$') { $val = $matches[1] }
            [Environment]::SetEnvironmentVariable($name, $val)
        }
    }
}

# Ghi đè các endpoint mặc định cho Local
$env:WHISPERX_API = "http://127.0.0.1:8001"
$env:TTS_API = "http://127.0.0.1:9880"
$env:DEMUCS_API = "local"
if (-not $env:TTS_ENGINE) { $env:TTS_ENGINE = "omnivoice" }
if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = "http://127.0.0.1:11434" }
if (-not $env:LLM_BACKEND) { $env:LLM_BACKEND = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "qwen2.5:14b" }
if (-not $env:DATA_DIR) { $env:DATA_DIR = "$ProjectRoot\data" }
if (-not $env:VRAM_PROFILE) { $env:VRAM_PROFILE = "24gb" }
# TTS parallelism: OmniVoice loads this many model replicas; orchestrator dispatches
# the same number of concurrent requests. STT/LLM are unloaded before phase-2 to free VRAM.
if (-not $env:OMNIVOICE_REPLICAS) { $env:OMNIVOICE_REPLICAS = "2" }
if (-not $env:TTS_CONCURRENCY) { $env:TTS_CONCURRENCY = "2" }
# OmniVoice quality: num_step (cao hơn = phát âm tự nhiên hơn; 64 vẫn ~20x realtime) + CFG scale.
if (-not $env:OMNIVOICE_NUM_STEP) { $env:OMNIVOICE_NUM_STEP = "64" }  # base model: higher = better quality
if (-not $env:OMNIVOICE_GUIDANCE) { $env:OMNIVOICE_GUIDANCE = "2.0" }
# Translation parallelism (client) + Ollama parallel slots (server, inherited by `ollama serve`).
if (-not $env:LLM_CONCURRENCY) { $env:LLM_CONCURRENCY = "4" }
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = "2" }

# Use venv site-packages for imports (avoid shm.dll loader in venv Python)
$env:PYTHONPATH = "$ProjectRoot\venv\Lib\site-packages;$ProjectRoot\GPT-SoVITS;$ProjectRoot\GPT-SoVITS\GPT_SoVITS"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
# Intel-Fortran/MKL (in torch/omnivoice) aborts with "forrtl: error (200)" when its console
# gets a CLOSE/CTRL event. Disable that handler so the TTS service survives window/console events.
$env:FOR_DISABLE_CONSOLE_CTRL_HANDLER = "1"
$env:GPT_SOVITS_DIR = "$ProjectRoot\GPT-SoVITS"
$env:OLLAMA_MODELS = "$ProjectRoot\models\ollama\models"
# Override model paths with absolute paths (relative paths break when services run from subdirs)
$env:WHISPER_MODEL_DIR = "$ProjectRoot\models\whisper"
# Base 646-lang OmniVoice model (it beat the VN fine-tune in A/B listening). To try the
# fine-tune instead, point this at "$ProjectRoot\models\omnivoice-vi".
$env:OMNIVOICE_MODEL_DIR = "$ProjectRoot\models\omnivoice"

# Add FFmpeg to PATH
$FFmpegBin = "$ProjectRoot\ffmpeg_extracted\ffmpeg-master-latest-win64-gpl\bin"
if (Test-Path $FFmpegBin) {
    $env:PATH = "$FFmpegBin;$env:PATH"
}
$env:PATH = "$ProjectRoot;$env:PATH"
# 1. Start WhisperX API
# GPU mode: cublas64_12.dll is preloaded from Ollama's cuda_v12 dir at startup.
# cudnn is disabled (torch's bundled stub is incomplete). ctranslate2 uses cuBLAS directly.
Write-Host "  -> Đang bật WhisperX (Port 8001, GPU mode)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app:app --port 8001" -WorkingDirectory "$ProjectRoot\whisperx-service" -WindowStyle Minimized

# 2. Start TTS API (GPT-SoVITS)
Write-Host "  -> Đang bật TTS Adapter (Port 9880)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app:app --port 9880" -WorkingDirectory "$ProjectRoot\tts-service" -WindowStyle Minimized

# 2.1 Start OmniVoice API
Write-Host "  -> Đang bật OmniVoice Adapter (Port 3900)..."
Start-Process -FilePath "$ProjectRoot\venv\Scripts\python.exe" -ArgumentList "-m uvicorn app:app --port 3900" -WorkingDirectory "$ProjectRoot\omnivoice-service" -WindowStyle Minimized

# 3. Start Orchestrator
Write-Host "  -> Đang bật Orchestrator (Port 8000)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn orchestrator.api:app --host 127.0.0.1 --port 8000" -WorkingDirectory "$ProjectRoot" -WindowStyle Minimized

# 4. Start vLLM (nếu dùng vllm)
if ($env:LLM_BACKEND -eq "vllm") {
    Write-Host "  -> Đang bật vLLM Server (Port 8080) với model $($env:LLM_MODEL)..."
    Start-Process -FilePath $PythonExe -ArgumentList "-m vllm.entrypoints.openai.api_server --model $($env:LLM_MODEL) --port 8080" -WorkingDirectory "$ProjectRoot" -WindowStyle Minimized
}

# 5. Start Ollama
if ($env:LLM_BACKEND -eq "ollama") {
    Write-Host "  -> Đang bật Ollama Server (Port 11434)..."
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    $ollamaExe = if ($ollamaCmd) { $ollamaCmd.Source } else { $null }
    if (-not $ollamaExe) { $ollamaExe = "C:\Users\ezycloudx-admin\AppData\Local\Programs\Ollama\ollama.exe" }
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c set OLLAMA_MODELS=$env:OLLAMA_MODELS && `"$ollamaExe`" serve" -WindowStyle Minimized
}

# 6. Start Frontend
Write-Host "  -> Đang bật Frontend (Port 5173)..."
Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory "$ProjectRoot\frontend" -WindowStyle Minimized

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host " Hệ thống đang chạy ở chế độ NATIVE." -ForegroundColor Green
Write-Host " Các cửa sổ Console ẩn/nhỏ đã được mở để chạy nền." -ForegroundColor Green
Write-Host " Vui lòng mở trình duyệt: http://localhost:5173" -ForegroundColor Green
Write-Host " Để tắt hệ thống, hãy đóng các cửa sổ Console tương ứng." -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
