import os, logging

logger = logging.getLogger(__name__)

def create_stt_service():
    provider = os.environ.get("STT_PROVIDER", "sherpa-onnx-online")
    logger.info(f"STT provider: {provider}")

    if provider == "sherpa-onnx-online":
        from .sherpa_onnx_online_stt import SherpaOnnxOnlineSTTService
        return SherpaOnnxOnlineSTTService(
            model_name=os.environ.get("STT_MODEL", "streaming-zipformer-small-en"),
            model_dir=os.environ.get("STT_MODEL_DIR", "/data/stt-models"),
            num_threads=int(os.environ.get("STT_NUM_THREADS", 4)),
            language=os.environ.get("STT_LANGUAGE", "en"),
        )
    elif provider == "faster-whisper":
        from pipecat.services.whisper import WhisperSTTService
        return WhisperSTTService(
            model=os.environ.get("STT_MODEL", "base.en"),
            device="cpu",
            compute_type="int8",
        )
    elif provider == "deepgram":
        from pipecat.services.deepgram import DeepgramSTTService
        return DeepgramSTTService(api_key=os.environ.get("STT_API_KEY", ""))
    elif provider == "openai":
        from pipecat.services.openai import OpenAISTTService
        import openai
        client = openai.AsyncOpenAI(
            api_key=os.environ.get("STT_API_KEY", "not-needed"),
            base_url=os.environ.get("STT_BASE_URL", None),
        )
        return OpenAISTTService(client=client)
    else:
        raise ValueError(f"Unknown STT_PROVIDER: {provider}")
