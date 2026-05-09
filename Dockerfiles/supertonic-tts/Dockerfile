FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libsndfile1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Clone the Supertonic repository
RUN git clone https://github.com/supertone-inc/supertonic.git /app/supertonic

# Install compatible numpy first
RUN pip install --no-cache-dir "numpy<2.0"

# Install PyTorch CPU version
RUN pip install --no-cache-dir torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu

# Install other Python dependencies with compatible versions
RUN pip install --no-cache-dir \
    transformers==4.36.2 \
    soundfile \
    librosa \
    wyoming \
    onnxruntime \
    huggingface-hub \
    flask \
    flask-cors

# Download ONNX models and voice styles from Hugging Face
RUN python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download( \
        repo_id='Supertone/supertonic-2', \
        allow_patterns=['onnx/*', 'voice_styles/*'], \
        local_dir='/app/supertonic/assets', \
        local_dir_use_symlinks=False \
    )"

# Set the entrypoint - script will be mounted from host
ENTRYPOINT ["python3", "/config/wyoming_supertonic.py"]
CMD ["--uri", "tcp://0.0.0.0:10500"]
