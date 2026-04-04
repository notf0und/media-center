#!/usr/bin/env python3
"""
OpenAI-compatible STT API for sherpa-onnx ASR.
Implements /v1/audio/transcriptions endpoint.
Runs inference directly (no Wyoming hop) for low latency.
"""
import logging
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.insert(0, "/data")
import model_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

MODEL_NAME = os.environ.get("SHERPA_MODEL", "cohere-transcribe")
MODEL_BASE_DIR = "/data"
NUM_THREADS = int(os.environ.get("SHERPA_NUM_THREADS", 4))
LANGUAGE = os.environ.get("SHERPA_LANGUAGE", "en")
API_PORT = int(os.environ.get("SHERPA_API_PORT", 5054))

_LOGGER.info("Loading model '%s' (language=%s, threads=%d) ...", MODEL_NAME, LANGUAGE, NUM_THREADS)
recognizer = model_registry.create_recognizer(MODEL_NAME, MODEL_BASE_DIR, NUM_THREADS, LANGUAGE)
_LOGGER.info("Model loaded.")


def convert_to_pcm16(audio_bytes: bytes, filename: str = "") -> tuple[bytes, int]:
    """Convert any audio format to 16kHz mono PCM16 WAV using ffmpeg."""
    suffix = ".tmp"
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm", ".opus"}:
            suffix = ext

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/data") as f:
        f.write(audio_bytes)
        input_path = f.name

    output_path = input_path + "_out.wav"

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", input_path,
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                "-acodec", "pcm_s16le",
                "-y",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")

        with wave.open(output_path, "rb") as wf:
            sample_rate = wf.getframerate()
            pcm_data = wf.readframes(wf.getnframes())

        return pcm_data, sample_rate

    except subprocess.TimeoutExpired:
        raise RuntimeError("Audio conversion timed out")
    finally:
        for p in (input_path, output_path):
            if os.path.exists(p):
                os.unlink(p)


def transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
    audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, audio_np)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


@app.route("/v1/audio/transcriptions", methods=["POST"])
def create_transcription():
    if "file" not in request.files:
        return jsonify({"error": {"message": "No audio file provided", "type": "invalid_request_error"}}), 400

    audio_file = request.files["file"]
    response_format = request.form.get("response_format", "json")
    language = request.form.get("language", LANGUAGE)
    temperature = request.form.get("temperature", "0")

    _LOGGER.info("Transcription request: file=%s, format=%s", audio_file.filename, response_format)

    try:
        audio_bytes = audio_file.read()
        pcm_data, sample_rate = convert_to_pcm16(audio_bytes, audio_file.filename or "")
        text = transcribe(pcm_data, sample_rate)
        _LOGGER.info("Result: %r", text)
    except Exception as e:
        _LOGGER.exception("Transcription error")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

    if response_format == "text":
        return text, 200, {"Content-Type": "text/plain"}
    elif response_format == "srt":
        return f"1\n00:00:00,000 --> 00:00:10,000\n{text}\n", 200, {"Content-Type": "text/plain"}
    elif response_format == "vtt":
        return f"WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n{text}\n", 200, {"Content-Type": "text/plain"}
    elif response_format == "verbose_json":
        return jsonify({
            "task": "transcribe",
            "language": language,
            "duration": 0.0,
            "text": text,
            "segments": [{
                "id": 0, "seek": 0, "start": 0.0, "end": 10.0,
                "text": text, "tokens": [],
                "temperature": float(temperature),
                "avg_logprob": 0.0, "compression_ratio": 1.0, "no_speech_prob": 0.0,
            }],
        })
    else:  # json (default)
        return jsonify({"text": text})


@app.route("/v1/models", methods=["GET"])
@app.route("/v1/audio/models", methods=["GET"])
def list_models():
    models = [
        {"id": name, "object": "model", "created": 1738022400, "owned_by": "k2-fsa"}
        for name in model_registry.MODELS
    ]
    return jsonify({"object": "list", "data": models})


@app.route("/health", methods=["GET"])
def health():
    try:
        # Quick smoke-test: create a stream on a zero-length signal
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, np.zeros(160, dtype=np.float32))
        recognizer.decode_stream(stream)
        return jsonify({"status": "healthy", "model": MODEL_NAME, "language": LANGUAGE})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.route("/", methods=["GET"])
@app.route("/v1", methods=["GET"])
def index():
    return jsonify({
        "name": "sherpa-onnx ASR OpenAI API",
        "version": "1.0.0",
        "model": MODEL_NAME,
        "language": LANGUAGE,
        "endpoints": {
            "transcriptions": "/v1/audio/transcriptions",
            "models": "/v1/models",
            "health": "/health",
        },
    })


if __name__ == "__main__":
    _LOGGER.info("Starting sherpa-onnx OpenAI API on port %d", API_PORT)
    app.run(host="0.0.0.0", port=API_PORT, threaded=True)
