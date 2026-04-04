import asyncio, logging, os, tarfile, urllib.request
import numpy as np
import sherpa_onnx
from pipecat.frames.frames import (
    Frame, AudioRawFrame, InputAudioRawFrame, TranscriptionFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.ai_services import STTService

logger = logging.getLogger(__name__)

ONLINE_MODELS = {
    "streaming-zipformer-small-en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-2023-10-17.tar.bz2",
        "dir": "sherpa-onnx-streaming-zipformer-small-2023-10-17",
        "type": "transducer",
        "encoder": "encoder-epoch-99-avg-1.onnx",
        "decoder": "decoder-epoch-99-avg-1.onnx",
        "joiner": "joiner-epoch-99-avg-1.onnx",
        "tokens": "tokens.txt",
    },
    "streaming-zipformer-en": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2",
        "dir": "sherpa-onnx-streaming-zipformer-en-2023-06-26",
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
    def __init__(self, model_name="streaming-zipformer-small-en", model_dir="/data/stt-models", num_threads=4, language="en"):
        super().__init__()
        self._model_name = model_name
        self._model_dir = model_dir
        self._num_threads = num_threads
        self._language = language
        self._speaking = False
        self._stream = None

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
                feature_dim=80,
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

    async def run_stt(self, audio: bytes):
        # Not used — we process incrementally in process_frame
        pass

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, UserStartedSpeakingFrame):
            self._stream = self._recognizer.create_stream()
            self._speaking = True
            logger.debug("Speech started — online recognizer stream created")
            await self.push_frame(frame, direction)

        elif isinstance(frame, InputAudioRawFrame) and self._speaking and self._stream:
            # Feed audio chunk to online recognizer in a thread (CPU inference)
            audio_np = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0
            # Pass the actual sample rate; sherpa-onnx resamples to 16kHz internally
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    self._stream.accept_waveform(frame.sample_rate, audio_np),
                    self._recognizer.decode_stream(self._stream),
                ),
            )
            # Don't forward audio frame (STT consumes it)

        elif isinstance(frame, UserStoppedSpeakingFrame):
            text = ""
            if self._stream:
                # Flush with tail silence padding
                tail = np.zeros(int(0.2 * 16000), dtype=np.float32)
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: (
                        self._stream.accept_waveform(16000, tail),
                        self._recognizer.decode_stream(self._stream),
                    ),
                )
                text = self._stream.result.text.strip()
                self._stream = None

            self._speaking = False
            logger.info(f"STT transcript: '{text}'")

            if text:
                await self.push_frame(
                    TranscriptionFrame(text=text, user_id="", timestamp=""),
                )
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)
