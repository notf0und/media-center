import os, logging
from pipecat.services.openai import OpenAILLMService

logger = logging.getLogger(__name__)

def create_llm_service():
    provider = os.environ.get("LLM_PROVIDER", "bonsai")
    logger.info(f"LLM provider: {provider}")

    base_url_map = {
        "bonsai": "http://localhost:8085/v1",
        "ollama": "http://localhost:11434/v1",
    }

    if provider in ("bonsai", "ollama", "openai-compat"):
        base_url = os.environ.get("LLM_BASE_URL", base_url_map.get(provider, "http://localhost:8085/v1"))
        api_key = os.environ.get("LLM_API_KEY", "not-needed")
        model = os.environ.get("LLM_MODEL", "Bonsai-1.7B")
        return OpenAILLMService(
            model=model,
            api_key=api_key,
            base_url=base_url,
            params=OpenAILLMService.InputParams(
                temperature=float(os.environ.get("LLM_TEMPERATURE", 0.5)),
                max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 256)),
            ),
        )
    elif provider == "openai":
        api_key = os.environ.get("LLM_API_KEY", "")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        return OpenAILLMService(model=model, api_key=api_key)
    elif provider == "anthropic":
        from pipecat.services.anthropic import AnthropicLLMService
        return AnthropicLLMService(
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", "claude-3-haiku-20240307"),
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
