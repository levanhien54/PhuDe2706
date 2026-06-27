FROM python:3.11-slim

# Install system dependencies (ffmpeg and build tools for audio processing)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    rubberband-cli \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Keep alive or run the orchestrator process
CMD ["python", "main.py"]
