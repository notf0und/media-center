FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl" \
    wyoming \
    huggingface_hub

WORKDIR /data
