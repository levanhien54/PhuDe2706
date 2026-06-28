#!/bin/bash
# =============================================================================
# Video Dubbing System — Native Setup (Không dùng Docker) cho Linux/macOS
# Yêu cầu trước khi chạy: Python 3.10+, Node.js, FFmpeg, NVIDIA GPU
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

step() { echo -e "\n\033[1;36m==> $1\033[0m"; }
ok()   { echo -e "  \033[1;32m[OK]\033[0m $1"; }
fail() { echo -e "  \033[1;31m[XX]\033[0m $1"; exit 1; }

# 1. Kiểm tra yêu cầu hệ thống
step "Kiểm tra yêu cầu hệ thống"

if ! command -v python3 &> /dev/null; then
    fail "Không tìm thấy Python. Vui lòng cài đặt Python 3.10+."
fi
ok "Python found."

if ! command -v node &> /dev/null; then
    fail "Không tìm thấy Node.js. Vui lòng cài đặt Node.js để chạy Frontend."
fi
ok "Node.js found."

if ! command -v ffmpeg &> /dev/null; then
    fail "Không tìm thấy FFmpeg. Vui lòng cài đặt FFmpeg."
fi
ok "FFmpeg found."

# 2. Thiết lập Môi trường Python (venv)
step "Thiết lập Python Virtual Environment"

if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "Đang tạo venv mới..."
    python3 -m venv venv || fail "Tạo venv thất bại."
fi
ok "Venv đã sẵn sàng tại ./venv"

PYTHON_EXE="$PROJECT_ROOT/venv/bin/python"
PIP_EXE="$PROJECT_ROOT/venv/bin/pip"

# Cập nhật pip
$PYTHON_EXE -m pip install --upgrade pip

# 3. Cài đặt PyTorch với CUDA (cu118)
step "Cài đặt PyTorch (CUDA 11.8)"
$PIP_EXE install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 || fail "Cài đặt PyTorch thất bại."

# 4. Cài đặt các thư viện hệ thống
step "Cài đặt Backend Dependencies"

$PIP_EXE install -r "$PROJECT_ROOT/orchestrator/requirements.txt"
$PIP_EXE install -r "$PROJECT_ROOT/whisperx-service/requirements.txt"
$PIP_EXE install -r "$PROJECT_ROOT/tts-service/requirements.txt"

# Cài đặt Demucs cục bộ để hỗ trợ native
$PIP_EXE install demucs

# Cài đặt thư viện cho ProPainter dependencies
echo -e "\n\033[1;36m==> Cài đặt phụ thuộc cho ProPainter\033[0m"
"$PIP_EXE" install einops scipy openmim
echo "Đang cài đặt mmcv qua openmim..."
"$PYTHON_EXE" -m mim install "mmcv>=2.0.0" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html || echo -e "\033[1;33mCảnh báo: Cài đặt mmcv thất bại.\033[0m"

# Cài đặt vLLM (Tuỳ chọn - Thay thế Ollama)
step "Cài đặt vLLM (Tuỳ chọn - Thay thế Ollama)"
echo -e "\033[1;33mLưu ý: Cài đặt vLLM có thể gặp lỗi nếu thiếu C++ compiler hoặc flash-attn. Hệ thống sẽ tự dùng Ollama nếu vLLM không khả dụng.\033[0m"
if $PIP_EXE install vllm; then
    ok "Đã cài đặt vLLM thành công."
else
    echo -e "  \033[1;33m[!!] Không thể cài đặt vLLM. Hãy đảm bảo dùng Ollama làm LLM_BACKEND.\033[0m"
fi

# 5. Khởi tạo thư mục và tải model Demucs sẵn
step "Tạo thư mục models và cấu hình"
mkdir -p models/{ollama,whisper,demucs,tts,propainter} data/{input,output,temp}

if [ ! -f "models/propainter/inference_propainter.py" ]; then
    echo "Đang tải mã nguồn ProPainter..."
    git clone https://github.com/sczhou/ProPainter.git models/propainter
fi

echo "Kích hoạt tải trọng số ProPainter (Khoảng 2GB)..."
"$PYTHON_EXE" -c "
import os, urllib.request
def dl(url, path):
    if not os.path.exists(path):
        print(f'Downloading {os.path.basename(path)}...')
        try: urllib.request.urlretrieve(url, path)
        except Exception as e: print(f'Lỗi khi tải {path}: {e}')
weights_dir = os.path.join('models', 'propainter', 'weights')
os.makedirs(weights_dir, exist_ok=True)
dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/ProPainter.pth', os.path.join(weights_dir, 'ProPainter.pth'))
dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/raft-things.pth', os.path.join(weights_dir, 'raft-things.pth'))
dl('https://github.com/sczhou/ProPainter/releases/download/v0.1.0/i3d_rgb_imagenet.pt', os.path.join(weights_dir, 'i3d_rgb_imagenet.pt'))
"
echo -e "  \033[1;32m[OK] Đã kiểm tra weights ProPainter.\033[0m"

if [ ! -f "$PROJECT_ROOT/models/latentsync/scripts/inference.py" ]; then
    step "Đang tải mã nguồn LatentSync (Lip-Sync)..."
    git clone https://github.com/bytedance/LatentSync.git "$PROJECT_ROOT/models/latentsync"
    # Cài đặt dependencies của LatentSync
    "$PIP_EXE" install -r "$PROJECT_ROOT/models/latentsync/requirements.txt"
    "$PIP_EXE" install huggingface_hub diffusers
fi

step "Kích hoạt tải trọng số LatentSync (có thể mất thời gian do file lớn)..."
"$PYTHON_EXE" -c "
import os
from huggingface_hub import snapshot_download
target_dir = os.path.join('$PROJECT_ROOT', 'models', 'latentsync', 'checkpoints')
os.makedirs(target_dir, exist_ok=True)
if not os.path.exists(os.path.join(target_dir, 'latentsync_unet.pt')):
    print('Downloading LatentSync weights from huggingface...')
    snapshot_download(repo_id='ByteDance/LatentSync', local_dir=target_dir)
"
ok "Đã kiểm tra weights LatentSync."

echo "Kích hoạt tải trước mô hình htdemucs..."
$PYTHON_EXE -c "from demucs.pretrained import get_model; get_model('htdemucs')"
ok "Đã tải htdemucs."

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/orchestrator/.env.example" "$PROJECT_ROOT/.env"
fi

# 6. Cài đặt Frontend
step "Cài đặt Frontend Dependencies"
cd "$PROJECT_ROOT/frontend"
npm install || fail "Lỗi khi chạy npm install."
cd "$PROJECT_ROOT"

step "SETUP HOÀN TẤT!"
echo -e "\033[1;32mChạy ./run_native.sh để khởi động hệ thống.\033[0m"
