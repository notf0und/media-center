#!/usr/bin/env python3
"""Wyoming STT server using sherpa-onnx OfflineRecognizer."""
import argparse
import asyncio
import logging
import sys

import numpy as np

sys.path.insert(0, "/data")
import model_registry

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

_LOGGER = logging.getLogger(__name__)

# Set at startup by main()
_recognizer = None
_model_name = "cohere-transcribe"
_language = "en"


class SherpaOnnxEventHandler(AsyncEventHandler):
    """Handles Wyoming protocol events for a single connection."""

    def __init__(self, wyoming_info: Info, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wyoming_info = wyoming_info
        self._audio_buffer: list[bytes] = []
        self._sample_rate: int = 16000

    async def handle_event(self, event):
        if Describe.is_type(event.type):
            await self.write_event(self._wyoming_info.event())

        elif Transcribe.is_type(event.type):
            # Acknowledge; nothing to do for offline recognizer
            pass

        elif AudioStart.is_type(event.type):
            audio_start = AudioStart.from_event(event)
            self._sample_rate = audio_start.rate
            self._audio_buffer = []
            _LOGGER.debug("AudioStart: rate=%d", self._sample_rate)

        elif AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            self._audio_buffer.append(chunk.audio)

        elif AudioStop.is_type(event.type):
            text = self._run_recognition()
            _LOGGER.info("Transcript: %r", text)
            await self.write_event(Transcript(text=text).event())

        return True

    def _run_recognition(self) -> str:
        if not self._audio_buffer:
            return ""

        raw_bytes = b"".join(self._audio_buffer)
        audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        stream = _recognizer.create_stream()
        stream.accept_waveform(self._sample_rate, audio_np)
        _recognizer.decode_stream(stream)
        return stream.result.text.strip()


def _build_wyoming_info() -> Info:
    return Info(
        asr=[
            AsrProgram(
                name="sherpa-onnx",
                description="sherpa-onnx ASR",
                attribution=Attribution(
                    name="k2-fsa",
                    url="https://github.com/k2-fsa/sherpa-onnx",
                ),
                installed=True,
                models=[
                    AsrModel(
                        name=_model_name,
                        description=_model_name,
                        attribution=Attribution(name="k2-fsa", url=""),
                        installed=True,
                        languages=[_language],
                    )
                ],
            )
        ]
    )


async def main_async(host: str, port: int) -> None:
    wyoming_info = _build_wyoming_info()

    server = AsyncServer.from_uri(f"tcp://{host}:{port}")
    _LOGGER.info("Wyoming server listening on %s:%d", host, port)

    await server.run(
        lambda *args, **kwargs: SherpaOnnxEventHandler(wyoming_info, *args, **kwargs)
    )


def main():
    global _recognizer, _model_name, _language

    parser = argparse.ArgumentParser(description="sherpa-onnx Wyoming ASR server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=10303)
    parser.add_argument("--model", default="cohere-transcribe")
    parser.add_argument("--model-dir", default="/data")
    parser.add_argument("--language", default="en")
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    _model_name = args.model
    _language = args.language

    _LOGGER.info(
        "Loading model '%s' (language=%s, threads=%d) ...",
        args.model,
        args.language,
        args.num_threads,
    )
    _recognizer = model_registry.create_recognizer(
        args.model, args.model_dir, args.num_threads, args.language
    )
    _LOGGER.info("Model loaded.")

    asyncio.run(main_async(args.host, args.port))


if __name__ == "__main__":
    main()
