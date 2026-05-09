FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    kokoro>=0.9.2 \
    wyoming \
    flask \
    flask-cors \
    soundfile \
    numpy

# Create cache directory for models (will auto-download on first use)
RUN mkdir -p /root/.cache/kokoro

# Scripts will be mounted from host
WORKDIR /app

CMD ["/bin/bash", "/data/start_services.sh"]
