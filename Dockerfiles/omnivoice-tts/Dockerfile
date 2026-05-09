FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first to avoid pulling the large CUDA build.
# omnivoice will see torch already satisfied and skip re-installing it.
RUN pip install --no-cache-dir \
    torch \
    torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# Install OmniVoice and the rest of the server dependencies.
RUN pip install --no-cache-dir \
    omnivoice \
    wyoming \
    flask \
    flask-cors \
    aiohttp \
    numpy

RUN mkdir -p /data

EXPOSE 10211 5055

CMD ["/bin/bash", "/data/start_services.sh"]
