FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    tar \
    bzip2 \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install gosu for privilege dropping (lightweight alternative to sudo in containers)
RUN curl -fsSL -o /usr/local/bin/gosu https://github.com/tianon/gosu/releases/download/1.17/gosu-amd64 && \
    chmod +x /usr/local/bin/gosu

# Install Python dependencies (including sherpa-onnx for embedded STT)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        sherpa-onnx \
        paho-mqtt \
        flask \
        flask-cors \
        watchdog \
        numpy \
        wyoming \
        supervisor

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
    cp "${EXTRACTED_DIR}/config.json.sample" /app/config.json.sample && \
    rm -rf /tmp/voicebm.tar.gz /tmp/voicebm_extract

# Copy our scripts (built into the image at build time)
COPY voicebm_wyoming_proxy.py /app/voicebm_wyoming_proxy.py
COPY voicebm_stt_engine.py /app/voicebm_stt_engine.py
COPY voicebm_stt_model_registry.py /app/voicebm_stt_model_registry.py
COPY config_generator.py /app/config_generator.py
COPY dashboard_patches.py /app/dashboard_patches.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/config_generator.py /app/dashboard_patches.py

# Data directory (mounted from host)
RUN mkdir -p /data

# Supervisord directories
RUN mkdir -p /etc/supervisor/conf.d

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
