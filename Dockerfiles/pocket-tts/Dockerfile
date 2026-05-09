FROM python:3.11-slim

# Install CPU-only torch first (pocket-tts requires torch 2.5+, GPU not needed)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    pocket-tts \
    wyoming \
    safetensors \
    zeroconf

WORKDIR /data
