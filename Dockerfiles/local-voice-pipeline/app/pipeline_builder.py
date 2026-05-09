#!/usr/bin/env python3
"""Assembles the Pipecat voice pipeline from environment configuration."""
import json, os, logging
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext

from .services.stt_factory import create_stt_service
from .services.llm_factory import create_llm_service
from .services.tts_factory import create_tts_service
from .services.entity_memory import EntityMemory
from .ha_client import build_ha_tools, call_ha_service, get_ha_state, HA_SYSTEM_PROMPT_SUFFIX
from .text_forwarder import SttTextForwarder, TtsTextForwarder

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a helpful voice assistant for a smart home. \
Be concise — voice responses should be 1-3 short sentences. \
Avoid markdown formatting. Do not use lists or bullet points. \
Do not restate or appreciate what the user says — make a quick inquiry or act immediately. \
Never describe the tool calls or steps you took — only state the final result to the user. \
Speak naturally as if in conversation."""

# Qwen3-based models (including Bonsai 1.7B) support a /nothink prefix to suppress
# chain-of-thought reasoning, which would otherwise waste tokens and slow responses.
QWEN3_SYSTEM_PROMPT_PREFIX = "/nothink\n\n"

MCP_TOOLS_SUFFIX = """
When controlling a device, call ha_search_entities first to find the exact entity_id, \
then call ha_call_service. Pick the entity whose friendly name most closely matches what \
the user said and act on it. Only ask for clarification if the user's request could mean \
fundamentally different device types (e.g. "office" alone could be a light, a TV, or a \
plug). Never guess entity IDs. Confirm the result in one short sentence only."""

MAX_TOOL_ITERATIONS = 3  # max tool calls per user turn before giving up
_SEARCH_FIRST_TOOL = "ha_search_entities"

async def build_pipeline(transport, ws_holder: dict | None = None) -> tuple:
    """Build a Pipecat Pipeline. Returns (pipeline, context, system_messages, memory).

    system_messages is the base [{"role":"system",...}] list used to reset conversation
    history on each new WebSocket connection (without entity memory).
    memory is an EntityMemory instance; call memory.inject_into_context(context) after
    each reset to restore the current known-entity hints.

    ws_holder: optional {"websocket": <ws>} dict updated by main.py on connect/disconnect.
    When provided, STT transcription and LLM response text are sent to the ESP32 as JSON
    WebSocket text frames for display.
    """

    # STT
    stt = create_stt_service()

    # LLM
    llm = create_llm_service()

    # TTS
    tts = create_tts_service()

    # Build system prompt — priority: SYSTEM_PROMPT_FILE > LLM_SYSTEM_PROMPT env > default
    prompt_file = os.environ.get("SYSTEM_PROMPT_FILE", "")
    if prompt_file and os.path.isfile(prompt_file):
        system_prompt = open(prompt_file).read().strip()
        logger.info(f"Loaded system prompt from: {prompt_file}")
    else:
        system_prompt = os.environ.get("LLM_SYSTEM_PROMPT", "") or DEFAULT_SYSTEM_PROMPT

    # Prepend /nothink for Qwen3-based models (Bonsai) to suppress chain-of-thought
    provider = os.environ.get("LLM_PROVIDER", "bonsai")
    model = os.environ.get("LLM_MODEL", "Bonsai-1.7B")
    if provider == "bonsai" or "bonsai" in model.lower() or "qwen3" in model.lower():
        system_prompt = QWEN3_SYSTEM_PROMPT_PREFIX + system_prompt

    # ── Tool integration ──────────────────────────────────────────────────────
    tools_list = []
    memory = EntityMemory()
    mcp_server_url = os.environ.get("MCP_SERVER_URL", "")
    ha_token = os.environ.get("HA_TOKEN", "")

    if mcp_server_url:
        # MCP integration: discover tools from the MCP server at startup
        from .services.mcp_client import MCPClient, DEFAULT_VOICE_TOOLS

        mcp_tools_env = os.environ.get("MCP_TOOLS", "")
        tool_names = (
            [n.strip() for n in mcp_tools_env.split(",") if n.strip()]
            if mcp_tools_env
            else DEFAULT_VOICE_TOOLS
        )

        verify_ssl = os.environ.get("MCP_SSL_VERIFY", "false").lower() == "true"
        mcp_client = MCPClient(mcp_server_url, verify_ssl=verify_ssl)
        try:
            await mcp_client.connect()
            await mcp_client.fetch_tools(names=tool_names)
            tools_list = mcp_client.to_openai_tools()

            # Register tool handlers (memory passed for post-search caching)
            for tool in mcp_client._tools:
                tool_name = tool["name"]
                llm.register_function(
                    tool_name,
                    _make_mcp_handler(tool_name, mcp_client, memory),
                )

            system_prompt += MCP_TOOLS_SUFFIX
            logger.info(f"MCP tools registered: {[t['name'] for t in mcp_client._tools]}")

        except Exception as exc:
            logger.error(f"MCP init failed ({exc}); falling back to direct HA tools")
            mcp_client = None
            if ha_token:
                tools_list, system_prompt = await _register_ha_direct(llm, system_prompt)

    elif ha_token:
        # Fallback: direct HA REST API tools (no MCP)
        tools_list, system_prompt = await _register_ha_direct(llm, system_prompt)

    # tool_choice="auto": Bonsai 1.7B at temp=0.1 follows the system prompt instruction.
    # "required" causes infinite loops on failure.
    tool_choice = "auto" if tools_list else None

    # Store base prompt in memory (before memory hints are appended) so it can
    # be used to rebuild the full system message after each entity discovery.
    memory.set_base_prompt(system_prompt)

    system_messages = [{"role": "system", "content": system_prompt}]
    context = OpenAILLMContext(
        messages=list(system_messages),
        tools=tools_list if tools_list else None,
        tool_choice=tool_choice,
    )
    context_aggregator = llm.create_context_aggregator(context)

    # Inject any entities already known from previous sessions
    if memory.inject_into_context(context):
        logger.info(f"EntityMemory: injected {len(memory)} known entities into system prompt")

    pipeline_stages = [
        transport.input(),
        stt,
        *(([SttTextForwarder(ws_holder)]) if ws_holder is not None else []),
        context_aggregator.user(),
        llm,
        *(([TtsTextForwarder(ws_holder)]) if ws_holder is not None else []),
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ]

    pipeline = Pipeline(pipeline_stages)

    return pipeline, context, system_messages, memory


def _make_mcp_handler(tool_name: str, mcp_client, memory: EntityMemory = None):
    """Return a Pipecat tool handler with per-turn iteration limit and entity memory caching."""

    async def handler(params) -> None:
        # Count tool calls since last user message to enforce iteration limit
        try:
            messages = params.context.messages
            user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
            last_user_idx = user_indices[-1] if user_indices else 0
            tool_calls_so_far = sum(1 for m in messages[last_user_idx:] if m.get("role") == "tool")
        except Exception:
            tool_calls_so_far = 0

        if tool_calls_so_far >= MAX_TOOL_ITERATIONS:
            logger.warning(f"Tool call limit reached ({MAX_TOOL_ITERATIONS}), bailing out")
            await params.result_callback("Error: could not complete the action after multiple attempts.")
            return

        result = await mcp_client.call_tool(tool_name, params.arguments)

        # After a search: persist newly discovered entities and refresh system prompt
        if tool_name == _SEARCH_FIRST_TOOL and memory is not None:
            try:
                data = json.loads(result) if isinstance(result, str) else result
                results = data.get("data", data).get("results", [])
                added = memory.add_from_search_results(results)
                if added:
                    memory.inject_into_context(params.context)
            except Exception as e:
                logger.debug(f"Memory update failed after search: {e}")

        await params.result_callback(result)

    handler.__name__ = tool_name
    return handler


async def _fetch_entity_hints(mcp_client) -> str:
    """Pre-fetch common controllable entities and return a compact hint string."""
    hints = []
    for domain in ("light", "switch", "cover", "climate", "media_player"):
        try:
            result = await mcp_client.call_tool(
                "ha_search_entities",
                {"query": "", "domain_filter": domain, "limit": 15},
            )
            import json
            data = json.loads(result) if isinstance(result, str) else result
            results = data.get("data", data).get("results", [])
            for r in results:
                eid = r.get("entity_id", "")
                name = r.get("friendly_name", "")
                state = r.get("state", "")
                hints.append(f"  {eid} ({name}, {state})")
        except Exception as e:
            logger.debug(f"Entity hint fetch failed for {domain}: {e}")
    return "\n".join(hints) if hints else ""


async def _register_ha_direct(llm, system_prompt: str) -> tuple[list, str]:
    tools_list = await build_ha_tools()

    async def _call_ha_service(params) -> None:
        result = await call_ha_service(**params.arguments)
        await params.result_callback(result)

    async def _get_ha_state(params) -> None:
        result = await get_ha_state(**params.arguments)
        await params.result_callback(result)

    llm.register_function("call_ha_service", _call_ha_service)
    llm.register_function("get_ha_state", _get_ha_state)

    system_prompt += "\n" + HA_SYSTEM_PROMPT_SUFFIX
    return tools_list, system_prompt
