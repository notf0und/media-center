import asyncio, logging, os, tarfile, time, urllib.request
from typing import AsyncGenerator
import numpy as np
import sherpa_onnx
from pipecat.frames.frames import (
    Frame, AudioRawFrame, TranscriptionFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import STTService

logger = logging.getLogger(__name__)

ONLINE_MODELS = {
    # NeMo Parakeet TDT 110M transducer — streaming English, ~430 MB
    # NOTE: requires window_size in encoder metadata; currently unsupported by sherpa-onnx 1.12.35
    "parakeet-tdt-110m": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet_tdt_transducer_110m-en-36000.tar.bz2",
        "dir": "sherpa-onnx-nemo-parakeet_tdt_transducer_110m-en-36000",
        "type": "transducer",
        "encoder": "encoder.onnx",
        "decoder": "decoder.onnx",
        "joiner": "joiner.onnx",
        "tokens": "tokens.txt",
        "normalize_samples": False,
        "feature_dim": 80,
    },
    # Zipformer English — ~350 MB, good accuracy (default)
    "streaming-zipformer-en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2",
        "dir": "sherpa-onnx-streaming-zipformer-en-2023-06-26",
        "type": "transducer",
        "encoder": "encoder-epoch-99-avg-1-chunk-16-left-128.onnx",
        "decoder": "decoder-epoch-99-avg-1-chunk-16-left-128.onnx",
        "joiner": "joiner-epoch-99-avg-1-chunk-16-left-128.onnx",
        "tokens": "tokens.txt",
    },
    # Zipformer small English — ~65 MB, fastest, lower accuracy
    "streaming-zipformer-small-en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-2023-10-17.tar.bz2",
        "dir": "sherpa-onnx-streaming-zipformer-small-2023-10-17",
        "type": "transducer",
        "encoder": "encoder-epoch-99-avg-1.onnx",
        "decoder": "decoder-epoch-99-avg-1.onnx",
        "joiner": "joiner-epoch-99-avg-1.onnx",
        "tokens": "tokens.txt",
    },
    "streaming-paraformer-zh-en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2",
        "dir": "sherpa-onnx-streaming-paraformer-bilingual-zh-en",
        "type": "paraformer",
        "encoder": "encoder.int8.onnx",
        "decoder": "decoder.int8.onnx",
        "tokens": "tokens.txt",
    },
}


class SherpaOnnxOnlineSTTService(STTService):
    def __init__(self, model_name="streaming-zipformer-en", model_dir="/data/stt-models", num_threads=4, language="en"):
        from pipecat.services.stt_service import STTSettings
        super().__init__(settings=STTSettings(model=model_name, language=language))
        self._model_name = model_name
        self._model_dir = model_dir
        self._num_threads = num_threads
        self._stream = None
        self._vad_start_time = None
        self._first_partial_time = None

        model_info = ONLINE_MODELS.get(model_name)
        if not model_info:
            raise ValueError(f"Unknown online STT model: {model_name}. Available: {list(ONLINE_MODELS.keys())}")

        self._model_path = os.path.join(model_dir, model_info["dir"])
        if not os.path.exists(self._model_path):
            self._download_model(model_info)

        self._recognizer = self._create_recognizer(model_info)
        logger.info(f"SherpaOnnxOnlineSTTService ready: {model_name}")

    def _download_model(self, model_info):
        os.makedirs(self._model_dir, exist_ok=True)
        url = model_info["url"]
        filename = os.path.join(self._model_dir, url.split("/")[-1])
        logger.info(f"Downloading {url}...")
        urllib.request.urlretrieve(url, filename)
        logger.info(f"Extracting {filename}...")
        with tarfile.open(filename, "r:bz2") as tar:
            tar.extractall(self._model_dir)
        os.remove(filename)
        logger.info(f"Model ready at {self._model_path}")

    def _create_recognizer(self, model_info):
        mtype = model_info["type"]
        p = self._model_path
        if mtype == "transducer":
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                encoder=os.path.join(p, model_info["encoder"]),
                decoder=os.path.join(p, model_info["decoder"]),
                joiner=os.path.join(p, model_info["joiner"]),
                tokens=os.path.join(p, model_info["tokens"]),
                num_threads=self._num_threads,
                sample_rate=16000,
                feature_dim=model_info.get("feature_dim", 80),
                normalize_samples=model_info.get("normalize_samples", True),
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2,
                rule3_min_utterance_length=300,
                decoding_method="greedy_search",
            )
        elif mtype == "paraformer":
            return sherpa_onnx.OnlineRecognizer.from_paraformer(
                encoder=os.path.join(p, model_info["encoder"]),
                decoder=os.path.join(p, model_info["decoder"]),
                tokens=os.path.join(p, model_info["tokens"]),
                num_threads=self._num_threads,
                sample_rate=16000,
                feature_dim=80,
                enable_endpoint_detection=True,
            )
        else:
            raise ValueError(f"Unknown model type: {mtype}")

    async def _handle_vad_user_started_speaking(self, frame: VADUserStartedSpeakingFrame):
        await super()._handle_vad_user_started_speaking(frame)
        self._stream = self._recognizer.create_stream()
        self._vad_start_time = time.monotonic()
        self._first_partial_time = None
        self._samples_fed = 0
        logger.info(f"STT: VAD started speaking")

    def _decode_ready(self, stream):
        """Feed audio and drain all ready decode steps; log first partial result."""
        while self._recognizer.is_ready(stream):
            self._recognizer.decode_stream(stream)
            if self._first_partial_time is None:
                partial = self._recognizer.get_result(stream).strip()
                if partial:
                    self._first_partial_time = time.monotonic()
                    elapsed_from_vad = self._first_partial_time - self._vad_start_time
                    logger.info(f"STT: first partial result after {elapsed_from_vad:.3f}s from VAD start: '{partial}'")

    async def _handle_vad_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        vad_stop_time = time.monotonic()
        elapsed_from_vad = vad_stop_time - (self._vad_start_time or vad_stop_time)
        logger.info(f"STT: VAD stopped after {elapsed_from_vad:.3f}s of speech")
        text = ""
        if self._stream:
            tail = np.zeros(int(0.2 * 16000), dtype=np.float32)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    self._stream.accept_waveform(16000, tail),
                    self._stream.input_finished(),
                    self._decode_ready(self._stream),
                ),
            )
            text = self._recognizer.get_result(self._stream).strip()
            self._stream = None

        final_time = time.monotonic()
        decode_latency = final_time - vad_stop_time
        logger.info(f"STT: final decode in {decode_latency*1000:.0f}ms samples_fed={self._samples_fed} → '{text}'")
        if text:
            await self.push_frame(
                TranscriptionFrame(text=text, user_id=self._user_id, timestamp=""),
            )
        await super()._handle_vad_user_stopped_speaking(frame)

    async def process_audio_frame(self, frame: AudioRawFrame, direction: FrameDirection):
        if not self._user_speaking or not self._stream:
            return
        audio_np = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0
        self._samples_fed += len(audio_np)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                self._stream.accept_waveform(frame.sample_rate, audio_np),
                self._decode_ready(self._stream),
            ),
        )

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        # Audio is processed incrementally in process_audio_frame; no-op here
        return
        yield  # noqa: make this an async generator
