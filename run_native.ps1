# =============================================================================
# Video Dubbing System — Native Run
# Khởi động toàn bộ hệ thống bằng PowerShell (thay thế docker-compose up)
# =============================================================================

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
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
            # Bỏ qua quotes nếu có
            if ($val -match '^"(.*)"$') { $val = $matches[1] }
            [Environment]::SetEnvironmentVariable($name, $val)
        }
    }
}

# Ghi đè các endpoint mặc định cho Local
$env:WHISPERX_API = "http://127.0.0.1:8001"
$env:TTS_API = "http://127.0.0.1:9880"
$env:DEMUCS_API = "local"
if (-not $env:TTS_ENGINE) { $env:TTS_ENGINE = "gpt_sovits" }
if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = "http://127.0.0.1:11434" }
if (-not $env:LLM_BACKEND) { $env:LLM_BACKEND = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "qwen2.5:14b" }

# 1. Start WhisperX API
Write-Host "  -> Đang bật WhisperX (Port 8001)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app:app --port 8001" -WorkingDirectory "$ProjectRoot\whisperx-service"

# 2. Start TTS API (GPT-SoVITS / OmniVoice adapter)
Write-Host "  -> Đang bật TTS Adapter (Port 9880)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app:app --port 9880" -WorkingDirectory "$ProjectRoot\tts-service"

# 3. Start Orchestrator
Write-Host "  -> Đang bật Orchestrator (Port 8000)..."
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn orchestrator.api:app --host 0.0.0.0 --port 8000" -WorkingDirectory "$ProjectRoot"

# 4. Start vLLM (nếu dùng vllm)
if ($env:LLM_BACKEND -eq "vllm") {
    Write-Host "  -> Đang bật vLLM Server (Port 8080) với model $($env:LLM_MODEL)..."
    Start-Process -FilePath $PythonExe -ArgumentList "-m vllm.entrypoints.openai.api_server --model $($env:LLM_MODEL) --port 8080" -WorkingDirectory "$ProjectRoot"
}

# 5. Start Frontend
Write-Host "  -> Đang bật Frontend (Port 5173)..."
Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory "$ProjectRoot\frontend"

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host " Hệ thống đang chạy ở chế độ NATIVE." -ForegroundColor Green
Write-Host " Các cửa sổ Console ẩn/nhỏ đã được mở để chạy nền." -ForegroundColor Green
Write-Host " Vui lòng mở trình duyệt: http://localhost:5173" -ForegroundColor Green
Write-Host " Để tắt hệ thống, hãy đóng các cửa sổ Console tương ứng." -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
