FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first to avoid downloading the heavy CUDA build
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        torch \
        torchaudio \
        --index-url https://download.pytorch.org/whl/cpu

# Clone VibeVoice repository
RUN git clone https://github.com/microsoft/VibeVoice.git .

# Install VibeVoice and its dependencies.
# --extra-index-url ensures the already-installed CPU torch is reused
# instead of pulling the CUDA build from PyPI.
RUN pip install --no-cache-dir -e . \
        --extra-index-url https://download.pytorch.org/whl/cpu

# Wyoming protocol library + API helpers
RUN pip install --no-cache-dir \
    wyoming \
    soundfile \
    flask \
    flask-cors

# HuggingFace model cache directory
RUN mkdir -p /data

# Wyoming port and OpenAI-compatible API port
EXPOSE 10302 5053

# Startup script is mounted from host at /data/start_services.sh
CMD ["/bin/bash", "/data/start_services.sh"]
