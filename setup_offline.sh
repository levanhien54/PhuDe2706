#!/bin/bash
# =============================================================================
# Video Dubbing System — Offline Setup (Cài đặt không cần Internet)
# Dành cho máy chủ Linux mới sau khi đã copy file từ máy cũ.
# Yêu cầu: Đã cài Python 3.10+, Node.js, FFmpeg, và có thư mục offline_wheels
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$PROJECT_ROOT"

function write_step() { echo -e "\n\033[1;36m==> $1\033[0m"; }
function write_ok()   { echo -e "  \033[1;32m[OK] $1\033[0m"; }
function write_fail() { echo -e "  \033[1;31m[XX] $1\033[0m"; exit 1; }

OFFLINE_DIR="$PROJECT_ROOT/offline_wheels"
if [ ! -d "$OFFLINE_DIR" ]; then
    write_fail "Không tìm thấy thư mục offline_wheels. Xin đảm bảo đã chạy pack_offline_bundle trên máy cũ và chép đầy đủ."
fi

# 1. Thiết lập Môi trường Python (venv)
write_step "Thiết lập Python Virtual Environment"

if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "Đang tạo venv mới..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then write_fail "Tạo venv thất bại."; fi
fi
write_ok "Venv đã sẵn sàng tại ./venv"

PIP_EXE="$PROJECT_ROOT/venv/bin/pip"

# 2. Cài đặt các thư viện từ thư mục Offline Wheels
write_step "Cài đặt Backend từ Offline Wheels (Siêu Tốc)"

BASE_PIP_ARGS="--no-index --find-links $OFFLINE_DIR"

echo "Cài đặt PyTorch..."
"$PIP_EXE" install $BASE_PIP_ARGS torch torchvision torchaudio

echo "Cài đặt Orchestrator..."
"$PIP_EXE" install $BASE_PIP_ARGS -r "$PROJECT_ROOT/orchestrator/requirements.txt"
echo "Cài đặt WhisperX..."
"$PIP_EXE" install $BASE_PIP_ARGS -r "$PROJECT_ROOT/whisperx-service/requirements.txt"
echo "Cài đặt TTS..."
"$PIP_EXE" install $BASE_PIP_ARGS -r "$PROJECT_ROOT/tts-service/requirements.txt"

echo "Cài đặt các gói phụ thuộc mở rộng..."
"$PIP_EXE" install $BASE_PIP_ARGS demucs vllm einops scipy huggingface_hub diffusers

if [ -f "$PROJECT_ROOT/models/latentsync/requirements.txt" ]; then
    echo "Cài đặt phụ thuộc LatentSync..."
    "$PIP_EXE" install $BASE_PIP_ARGS -r "$PROJECT_ROOT/models/latentsync/requirements.txt"
fi

write_ok "Đã cài đặt xong thư viện Backend."

# 3. Môi trường và Models
write_step "Kiểm tra cấu hình"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/orchestrator/.env.example" "$PROJECT_ROOT/.env"
fi

# 4. Cài đặt Frontend
write_step "Cài đặt Frontend"
cd "$PROJECT_ROOT/frontend"
npm install
if [ $? -ne 0 ]; then write_fail "Lỗi khi chạy npm install."; fi
cd "$PROJECT_ROOT"

write_step "OFFLINE SETUP HOÀN TẤT!"
echo -e "\033[1;32mBạn đã cài đặt siêu tốc thành công! Chạy ./run_native.sh để khởi động hệ thống.\033[0m"
