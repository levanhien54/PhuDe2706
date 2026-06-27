FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 GPT_SOVITS_DIR=/app/GPT-SoVITS

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg git curl \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
# Pin a known revision for reproducibility; update as needed.
RUN git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git /app/GPT-SoVITS

RUN pip3 install --no-cache-dir torch==2.1.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118 \
    && pip3 install --no-cache-dir -r /app/GPT-SoVITS/requirements.txt

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 9880
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=180s \
    CMD curl -f http://localhost:9880/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9880"]
