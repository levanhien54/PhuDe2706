#!/usr/bin/env bash
# =============================================================================
# Video Dubbing System — One-Command Setup (Linux / macOS)
# Chạy: bash setup.sh [--llm-model qwen2.5:14b] [--vram 16gb] [--with-lipsync]
# =============================================================================

set -euo pipefail

LLM_MODEL="qwen2.5:14b"
VRAM_PROFILE="16gb"
WITH_LIPSYNC=false
SKIP_PULL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --llm-model)   LLM_MODEL="$2";   shift 2 ;;
        --vram)        VRAM_PROFILE="$2"; shift 2 ;;
        --with-lipsync) WITH_LIPSYNC=true; shift ;;
        --skip-pull)   SKIP_PULL=true;   shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

step()  { echo; echo "==> $*"; }
ok()    { echo "  [OK] $*"; }
warn()  { echo "  [!!] $*"; }
fail()  { echo "  [XX] $*"; exit 1; }

# ------------------------------------------------------------------
# 1. Prerequisites
# ------------------------------------------------------------------
step "Kiểm tra prerequisites"

command -v docker >/dev/null 2>&1 || fail "Docker chưa được cài. Xem: https://docs.docker.com/engine/install/"
ok "Docker: $(docker --version)"

if docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    ok "NVIDIA GPU khả dụng."
else
    warn "GPU không khả dụng — chạy CPU mode (chậm hơn nhiều)."
    warn "Cài NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/"
fi

# ------------------------------------------------------------------
# 2. File .env
# ------------------------------------------------------------------
step "Cấu hình môi trường"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    cp "$PROJECT_ROOT/orchestrator/.env.example" "$PROJECT_ROOT/.env"
    sed -i "s/LLM_MODEL=.*/LLM_MODEL=$LLM_MODEL/" "$PROJECT_ROOT/.env"
    sed -i "s/VRAM_PROFILE=.*/VRAM_PROFILE=$VRAM_PROFILE/" "$PROJECT_ROOT/.env"
    ok ".env tạo từ .env.example"
else
    ok ".env đã tồn tại — giữ nguyên."
fi

# ------------------------------------------------------------------
# 3. Thư mục models/
# ------------------------------------------------------------------
step "Tạo thư mục"
mkdir -p models/{ollama,whisper,demucs,tts,omnivoice,lipsync} data/{input,output,temp}
ok "Thư mục sẵn sàng."

# ------------------------------------------------------------------
# 4. Pull Docker images
# ------------------------------------------------------------------
if [[ "$SKIP_PULL" == false ]]; then
    step "Kéo Docker images (10-30 phút lần đầu)"
    PROFILES=""
    [[ "$WITH_LIPSYNC" == true ]] && PROFILES="--profile lipsync"
    docker compose $PROFILES pull
    ok "Tất cả images đã kéo."
else
    warn "Bỏ qua bước pull (--skip-pull)."
fi

# ------------------------------------------------------------------
# 5. LLM model qua Ollama
# ------------------------------------------------------------------
step "Tải LLM: $LLM_MODEL"
docker compose up -d ollama
sleep 10

tries=0
until docker inspect --format='{{.State.Health.Status}}' ai_dubbing_ollama 2>/dev/null | grep -q healthy; do
    sleep 5; ((tries++))
    echo "  Ollama khởi động... ($tries/12)"
    [[ $tries -ge 12 ]] && warn "Ollama chưa healthy, tiếp tục thử..." && break
done

docker exec ai_dubbing_ollama ollama pull "$LLM_MODEL"
ok "LLM $LLM_MODEL → models/ollama/"

# ------------------------------------------------------------------
# 6. Whisper model
# ------------------------------------------------------------------
step "Tải Whisper Large-v3 (~3 GB)"
docker compose up -d whisperx
sleep 15

tries=0
until curl -sf http://localhost:8001/health >/dev/null 2>&1; do
    sleep 10; ((tries++))
    echo "  Chờ WhisperX... ($tries/18)"
    [[ $tries -ge 18 ]] && warn "WhisperX timeout — model có thể chưa tải xong" && break
done
ok "Whisper model → models/whisper/"

# ------------------------------------------------------------------
# 7. Demucs model
# ------------------------------------------------------------------
step "Tải Demucs htdemucs (~80 MB)"
docker compose up -d demucs
sleep 5

docker exec ai_dubbing_demucs python3 -c "
from demucs.pretrained import get_model
get_model('htdemucs')
print('Demucs OK')
" 2>&1 || warn "Demucs tự tải khi chạy lần đầu."
ok "Demucs model → models/demucs/"

# ------------------------------------------------------------------
# 8. OmniVoice model
# ------------------------------------------------------------------
step "Tải OmniVoice (~2 GB)"
docker compose up -d omnivoice

tries=0
until curl -sf http://localhost:3900/health >/dev/null 2>&1; do
    sleep 10; ((tries++))
    echo "  Chờ OmniVoice... ($tries/18)"
    [[ $tries -ge 18 ]] && warn "OmniVoice timeout" && break
done
ok "OmniVoice model → models/omnivoice/"

# ------------------------------------------------------------------
# 9. Dừng containers
# ------------------------------------------------------------------
step "Dừng containers tạm"
docker compose down
ok "Dừng xong."

# ------------------------------------------------------------------
# 10. Tóm tắt
# ------------------------------------------------------------------
echo
echo "================================================================"
echo " SETUP HOÀN TẤT!"
echo "================================================================"
echo
echo " Models đã tải:"
echo "   LLM        → models/ollama/   ($LLM_MODEL)"
echo "   Whisper    → models/whisper/  (large-v3)"
echo "   Demucs     → models/demucs/   (htdemucs)"
echo "   OmniVoice  → models/omnivoice/"
echo
echo " Để chạy:"
echo "   1. Bỏ video vào:   data/input/"
echo "   2. Chạy:           docker compose up"
echo "   3. Kết quả:        data/output/"
if [[ "$WITH_LIPSYNC" == true ]]; then
    echo "   Lip-sync:          docker compose --profile lipsync up"
fi
echo
echo " Options:"
echo "   bash setup.sh --llm-model gemma2:27b --vram 24gb --with-lipsync"
echo "================================================================"
