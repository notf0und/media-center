#!/usr/bin/env python3
"""Assembles the Pipecat voice pipeline from environment configuration."""
import os, logging
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext, OpenAILLMContextAggregator

from .services.stt_factory import create_stt_service
from .services.llm_factory import create_llm_service
from .services.tts_factory import create_tts_service
from .ha_client import build_ha_tools, HA_SYSTEM_PROMPT_SUFFIX
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a helpful voice assistant for a smart home. \
Be concise — voice responses should be 1-3 short sentences. \
Avoid markdown formatting. Do not use lists or bullet points.
Speak naturally as if in conversation."""

async def build_pipeline(transport):
    """Build and return a Pipecat Pipeline for a single WebSocket connection."""

    # STT
    stt = create_stt_service()

    # LLM
    llm = create_llm_service()

    # TTS
    tts = create_tts_service()

    # Build system prompt
    system_prompt = os.environ.get("LLM_SYSTEM_PROMPT", "") or DEFAULT_SYSTEM_PROMPT
    ha_tools = []
    ha_token = os.environ.get("HA_TOKEN", "")
    if ha_token:
        ha_tools = await build_ha_tools()
        system_prompt += "\n" + HA_SYSTEM_PROMPT_SUFFIX

    # Conversation context
    messages = [{"role": "system", "content": system_prompt}]
    context = OpenAILLMContext(messages=messages, tools=ha_tools if ha_tools else None)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    return pipeline
