FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 GPT_SOVITS_DIR=/app/GPT-SoVITS

# build-essential + cmake + python3-dev: several GPT-SoVITS deps (e.g. pyopenjtalk)
# build native wheels from source and need a C/C++ toolchain + cmake.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev build-essential cmake ffmpeg git curl \
    && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
# Pin a known revision for reproducibility; update as needed.
RUN git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git /app/GPT-SoVITS

RUN pip3 install --no-cache-dir "setuptools<70" wheel cython numpy
# torch 2.4.x (cu121, matching the CUDA 12.1 base) — current GPT-SoVITS main needs
# a recent torch (pytorch-lightning>=2.4); older torch makes pip backtrack forever
# on the unpinned x_transformers.
RUN pip3 install --no-cache-dir torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
# pyopenjtalk's sdist reports its metadata name as "unknown", which breaks pip's
# resolver ("inconsistent name"). Build/install it WITHOUT build isolation first
# (build deps + cmake are present), then drop it from the requirements file so the
# bulk install doesn't try to re-resolve it from the index.
RUN pip3 install --no-cache-dir --no-build-isolation pyopenjtalk \
    && sed -i '/pyopenjtalk/d' /app/GPT-SoVITS/requirements.txt \
    && pip3 install --no-cache-dir -r /app/GPT-SoVITS/requirements.txt

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 9880
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=180s \
    CMD curl -f http://localhost:9880/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9880"]
