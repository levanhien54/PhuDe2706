#!/bin/bash
# =============================================================================
# Video Dubbing System — Native Run cho Linux/macOS
# Khởi động toàn bộ hệ thống bằng bash (thay thế docker-compose up)
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

PYTHON_EXE="$PROJECT_ROOT/venv/bin/python"

if [ ! -f "$PYTHON_EXE" ]; then
    echo -e "\033[1;31m[XX] Không tìm thấy venv. Vui lòng chạy ./setup_native.sh trước.\033[0m"
    exit 1
fi

echo -e "\033[1;36mKhởi động các dịch vụ trong background...\033[0m"

# Nạp file .env (nếu có) — parse an toàn từng dòng KEY=VALUE. KHÔNG dot-source dưới `set -a`:
# dot-source THỰC THI nội dung .env, nên một value chứa `$(...)`/backtick/`;` sẽ chạy như lệnh.
if [ -f "$PROJECT_ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # bỏ qua dòng trống và comment
        case "$line" in
            ''|'#'*) continue ;;
        esac
        # chỉ nhận dòng dạng KEY=VALUE
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac
        key="${line%%=*}"
        val="${line#*=}"
        # trim khoảng trắng quanh key
        key="$(printf '%s' "$key" | tr -d '[:space:]')"
        [ -z "$key" ] && continue
        # trim khoảng trắng đầu/cuối value
        val="${val#"${val%%[![:space:]]*}"}"
        val="${val%"${val##*[![:space:]]}"}"
        # bỏ cặp dấu nháy kép/đơn bao ngoài value (nếu có)
        case "$val" in
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        export "$key=$val"
    done < "$PROJECT_ROOT/.env"
fi

# Ghi đè các endpoint mặc định cho Local
export WHISPERX_API="http://127.0.0.1:8001"
export TTS_API="http://127.0.0.1:9880"
export DEMUCS_API="local"
export TTS_ENGINE="${TTS_ENGINE:-omnivoice}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export LLM_BACKEND="${LLM_BACKEND:-ollama}"
export LLM_MODEL="${LLM_MODEL:-qwen2.5:14b}"

# 1. Start WhisperX API
echo "  -> Đang bật WhisperX (Port 8001)..."
cd "$PROJECT_ROOT/whisperx-service"
nohup $PYTHON_EXE -m uvicorn app:app --port 8001 > whisperx.log 2>&1 &
WHISPERX_PID=$!

# 2. Start TTS API
echo "  -> Đang bật TTS Adapter (Port 9880)..."
cd "$PROJECT_ROOT/tts-service"
nohup $PYTHON_EXE -m uvicorn app:app --port 9880 > tts.log 2>&1 &
TTS_PID=$!

# 3. Start Orchestrator
echo "  -> Đang bật Orchestrator (Port 8000)..."
cd "$PROJECT_ROOT"
nohup $PYTHON_EXE -m uvicorn orchestrator.api:app --host 127.0.0.1 --port 8000 > orchestrator.log 2>&1 &
ORCH_PID=$!

# 4. Start vLLM (nếu dùng vllm)
VLLM_PID=""
if [ "$LLM_BACKEND" = "vllm" ]; then
    echo "  -> Đang bật vLLM Server (Port 8080) với model $LLM_MODEL..."
    cd "$PROJECT_ROOT"
    nohup $PYTHON_EXE -m vllm.entrypoints.openai.api_server --model "$LLM_MODEL" --port 8080 > vllm.log 2>&1 &
    VLLM_PID=$!
fi

# 5. Start Frontend
echo "  -> Đang bật Frontend (Port 5173)..."
cd "$PROJECT_ROOT/frontend"
nohup npm run dev > frontend.log 2>&1 &
FRONTEND_PID=$!

cd "$PROJECT_ROOT"

echo ""
echo -e "\033[1;32m=================================================================\033[0m"
echo -e "\033[1;32m Hệ thống đang chạy ở chế độ NATIVE.\033[0m"
echo -e "\033[1;32m Vui lòng mở trình duyệt: http://localhost:5173\033[0m"
echo -e "\033[1;32m Để tắt hệ thống, chạy lệnh: kill $WHISPERX_PID $TTS_PID $ORCH_PID $VLLM_PID $FRONTEND_PID\033[0m"
echo -e "\033[1;32m=================================================================\033[0m"
