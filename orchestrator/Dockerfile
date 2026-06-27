# GPU base so PaddleOCR can use CUDA. CUDA 11.8 + cuDNN8 matches the
# paddlepaddle-gpu cu118 wheel installed below.
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# System dependencies: Python, ffmpeg, OpenCV libs, rubberband (pyrubberband), curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    ffmpeg libgl1 libglib2.0-0 rubberband-cli curl \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
# PaddlePaddle GPU wheel for CUDA 11.8 comes from Paddle's own package index
# (not PyPI). If this index is unreachable in your region, swap to the matching
# wheel from https://www.paddlepaddle.org.cn/install/quick
RUN pip3 install --no-cache-dir paddlepaddle-gpu==2.6.1 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ \
    && pip3 install --no-cache-dir -r requirements.txt

COPY . .

# Health check: verify orchestrator can import config
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "from orchestrator.config import get_settings; get_settings()" || exit 1

CMD ["python", "-m", "orchestrator.main"]
