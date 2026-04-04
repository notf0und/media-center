FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y wget bzip2 ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir sherpa-onnx wyoming flask flask-cors soundfile numpy

RUN mkdir -p /data

EXPOSE 10303 5054

CMD ["/bin/bash", "/data/start_services.sh"]
