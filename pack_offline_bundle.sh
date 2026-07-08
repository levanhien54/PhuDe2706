#!/bin/bash
# =============================================================================
# Video Dubbing System — Pack Offline Bundle (Linux/macOS)
# Mô tả: Thu thập toàn bộ các file wheel của Python để chuẩn bị cho setup offline
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$PROJECT_ROOT"

function write_step() { echo -e "\n\033[1;36m==> $1\033[0m"; }
function write_ok()   { echo -e "  \033[1;32m[OK] $1\033[0m"; }
function write_fail() { echo -e "  \033[1;31m[XX] $1\033[0m"; exit 1; }

PIP_EXE="$PROJECT_ROOT/venv/bin/pip"
if [ ! -f "$PIP_EXE" ]; then
    write_fail "Không tìm thấy venv nội bộ. Hãy chạy setup_native.sh trên máy này trước khi đóng gói!"
fi

OFFLINE_DIR="$PROJECT_ROOT/offline_wheels"
mkdir -p "$OFFLINE_DIR"

write_step "Tải build tools (pip/setuptools/wheel — cần để build sdist như demucs, whisperx khi cài offline)..."
"$PIP_EXE" download pip setuptools wheel -d "$OFFLINE_DIR"

write_step "Tải PyTorch CUDA 11.8 Wheels..."
"$PIP_EXE" download torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -d "$OFFLINE_DIR"

write_step "Tải Backend Dependencies..."
"$PIP_EXE" download -r "$PROJECT_ROOT/orchestrator/requirements.txt" -d "$OFFLINE_DIR"
"$PIP_EXE" download -r "$PROJECT_ROOT/whisperx-service/requirements.txt" -d "$OFFLINE_DIR"
# whisperx pins a git HEAD (newer than PyPI); build it into an sdist so the offline installer
# can pull it by name with --pre (mirror pack_offline_bundle.ps1).
"$PIP_EXE" download "git+https://github.com/m-bain/whisperx.git" -d "$OFFLINE_DIR"
"$PIP_EXE" download -r "$PROJECT_ROOT/tts-service/requirements.txt" -d "$OFFLINE_DIR"
"$PIP_EXE" download -r "$PROJECT_ROOT/omnivoice-service/requirements.txt" -d "$OFFLINE_DIR"
"$PIP_EXE" download demucs einops scipy openmim huggingface_hub diffusers -d "$OFFLINE_DIR"
# vLLM tách riêng, best-effort: 1 wheel không resolve được (vd trên Windows) sẽ làm pip hủy
# CẢ lệnh và không tải gói nào — không được làm hỏng cả gói offline (mirror setup_native.ps1).
if ! "$PIP_EXE" download vllm -d "$OFFLINE_DIR"; then
    echo -e "  \033[1;33m[!!] Không tải được vLLM wheel — bỏ qua (máy đích sẽ dùng Ollama làm LLM_BACKEND).\033[0m"
fi

write_step "Tải MMCV Wheel..."
"$PIP_EXE" download "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html -d "$OFFLINE_DIR"

if [ -f "$PROJECT_ROOT/models/latentsync/requirements.txt" ]; then
    "$PIP_EXE" download -r "$PROJECT_ROOT/models/latentsync/requirements.txt" -d "$OFFLINE_DIR"
fi

write_ok "Thu thập Python wheels thành công tại $OFFLINE_DIR!"
echo -e "\033[1;33mBây giờ bạn có thể nén thư mục dự án này (BỎ QUA thư mục venv, data/input, data/output) để copy sang máy chủ mới.\033[0m"
