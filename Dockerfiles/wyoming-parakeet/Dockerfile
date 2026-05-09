FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including ffmpeg for audio conversion
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Clone the wyoming-onnx-asr repository
RUN git clone https://github.com/tboby/wyoming-onnx-asr.git .

# Install Python dependencies using pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir onnxruntime && \
    pip install --no-cache-dir .

# Install additional dependencies for OpenAI API
RUN pip install --no-cache-dir \
    flask \
    flask-cors

# Create data directory
RUN mkdir -p /data

# Expose Wyoming protocol port and OpenAI API port
EXPOSE 10300 5052

# Set entrypoint - script will be mounted from host
CMD ["/bin/bash", "/data/start_services.sh"]
