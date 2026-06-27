FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev ffmpeg git curl pkg-config \
    libavformat-dev libavcodec-dev libavdevice-dev \
    libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir torch==2.0.0 torchaudio==2.0.0 --index-url https://download.pytorch.org/whl/cu118 \
    && pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
