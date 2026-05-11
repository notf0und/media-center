#!/usr/bin/env python3
"""
Embedded STT engine for voicebm using sherpa-onnx OfflineRecognizer.

This allows voicebm to handle speech-to-text internally without depending on
an external parakeet/sherpa-onnx-asr service.

Model selection via environment variables:
  VOICEBM_STT_MODEL    - Model name (default: cohere-transcribe)
  VOICEBM_STT_LANGUAGE - Language (default: en)
  VOICEBM_STT_THREADS  - CPU threads (default: 4)
"""

import logging
import numpy as np
import sys
from typing import Optional

# Import from centralized registry to avoid duplication
from voicebm_stt_model_registry import (
    get_model_info,
    create_recognizer,
    download_model,
)

_LOGGER = logging.getLogger(__name__)

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None


class VoiceBMSTTEngine:
    """Embedded STT engine using sherpa-onnx OfflineRecognizer."""

    def __init__(
        self,
        model_name: str = "cohere-transcribe",
        model_dir: str = "/data/stt-models",
        language: str = "en",
        num_threads: int = 4,
    ):
        """Initialize STT engine with a sherpa-onnx model."""
        if sherpa_onnx is None:
            raise RuntimeError("sherpa-onnx not installed")

        self.model_name = model_name
        self.model_dir = model_dir
        self.language = language
        self.num_threads = num_threads

        self._recognizer = create_recognizer(
            model_name=model_name,
            model_base_dir=model_dir,
            language=language,
            num_threads=num_threads,
        )
        _LOGGER.info(
            f"VoiceBM STT Engine initialized: {model_name}, language={language}"
        )

    def recognize(
        self, audio_data: bytes, sample_rate: int = 16000
    ) -> str:
        """Recognize speech from audio bytes.

        Args:
            audio_data: Raw PCM audio data (int16)
            sample_rate: Sample rate in Hz (default: 16000)

        Returns:
            Transcribed text
        """
        try:
            # Convert bytes to numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(
                np.float32
            ) / 32768.0

            # Create stream and recognize
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, audio_np)
            self._recognizer.decode_stream(stream)

            text = stream.result.text.strip()
            _LOGGER.debug(f"STT recognized: {text!r}")
            return text
        except Exception as e:
            _LOGGER.error(f"STT recognition error: {e}", exc_info=True)
            return ""


# Global instance (initialized in voicebm_wyoming_proxy.py)
_STT_ENGINE: Optional[VoiceBMSTTEngine] = None


def get_stt_engine() -> Optional[VoiceBMSTTEngine]:
    """Get or create the global STT engine."""
    global _STT_ENGINE
    return _STT_ENGINE


def init_stt_engine(
    model_name: str = "cohere-transcribe",
    model_dir: str = "/data/stt-models",
    language: str = "en",
    num_threads: int = 4,
) -> VoiceBMSTTEngine:
    """Initialize the global STT engine."""
    global _STT_ENGINE
    _STT_ENGINE = VoiceBMSTTEngine(
        model_name=model_name,
        model_dir=model_dir,
        language=language,
        num_threads=num_threads,
    )
    return _STT_ENGINE


def download_stt_model(model_name: str, base_dir: str) -> None:
    """Download and extract STT model if not already present.

    Args:
        model_name: Model name from MODELS registry
        base_dir: Base directory to download models into
    
    Delegates to centralized registry function to avoid duplication.
    """
    download_model(model_name, base_dir)
