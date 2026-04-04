import os, logging, openai
from pipecat.services.openai import OpenAITTSService

logger = logging.getLogger(__name__)

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
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        return OpenAITTSService(
            client=client,
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
