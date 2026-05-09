import os, logging
from pipecat.services.openai import OpenAITTSService
import pipecat.services.openai.tts as _openai_tts

logger = logging.getLogger(__name__)

def _register_voice(voice: str):
    """Add a non-standard voice (e.g. kokoro) to pipecat's VALID_VOICES dict."""
    if voice not in _openai_tts.VALID_VOICES:
        _openai_tts.VALID_VOICES[voice] = voice  # type: ignore[assignment]

def create_tts_service():
    provider = os.environ.get("TTS_PROVIDER", "kokoro-http")
    # Must match WEBSOCKET_OUTPUT_SAMPLE_RATE (ESP32 speaker rate configured in ESPHome)
    sample_rate = int(os.environ.get("TTS_SAMPLE_RATE", 24000))
    logger.info(f"TTS provider: {provider}, sample_rate={sample_rate}")

    if provider in ("kokoro-http", "openai-tts", "openai-compat-tts"):
        base_url = os.environ.get("TTS_BASE_URL", "http://localhost:5051")
        api_key = os.environ.get("TTS_API_KEY", "not-needed")
        voice = os.environ.get("TTS_VOICE", "af_sky")
        model = os.environ.get("TTS_MODEL", "kokoro")
        _register_voice(voice)
        return OpenAITTSService(
            api_key=api_key,
            base_url=base_url,
            voice=voice,
            model=model,
            sample_rate=sample_rate,
        )
    elif provider == "openai":
        api_key = os.environ.get("TTS_API_KEY", "")
        voice = os.environ.get("TTS_VOICE", "alloy")
        return OpenAITTSService(api_key=api_key, voice=voice, sample_rate=sample_rate)
    elif provider == "elevenlabs":
        from pipecat.services.elevenlabs import ElevenLabsTTSService
        return ElevenLabsTTSService(
            api_key=os.environ.get("TTS_API_KEY", ""),
            voice_id=os.environ.get("TTS_VOICE", ""),
        )
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {provider}")
