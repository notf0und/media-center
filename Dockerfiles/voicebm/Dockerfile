FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    tar \
    bzip2 \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        sherpa-onnx \
        paho-mqtt \
        flask \
        flask-cors \
        watchdog \
        numpy \
        wyoming

# Download the latest VoiceBM release and extract templates + scripts
RUN LATEST_URL=$(curl -fsSL https://api.github.com/repos/cybericebyte/VoiceBM/releases/latest \
        | jq -r '.assets[] | select(.name | endswith(".tar.gz")) | .browser_download_url') && \
    echo "Downloading VoiceBM from: ${LATEST_URL}" && \
    curl -fsSL -o /tmp/voicebm.tar.gz "${LATEST_URL}" && \
    mkdir -p /tmp/voicebm_extract && \
    tar -xzf /tmp/voicebm.tar.gz -C /tmp/voicebm_extract && \
    EXTRACTED_DIR=$(find /tmp/voicebm_extract -mindepth 1 -maxdepth 1 -type d | head -1) && \
    cp -r "${EXTRACTED_DIR}/templates" /app/templates && \
    cp "${EXTRACTED_DIR}/templates/global/sherpa_embed.py" /app/sherpa_embed.py && \
    rm -rf /tmp/voicebm.tar.gz /tmp/voicebm_extract

# Copy our scripts (built into the image at build time)
COPY voicebm_wyoming_proxy.py /app/voicebm_wyoming_proxy.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Data directory (mounted from host)
RUN mkdir -p /data

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
