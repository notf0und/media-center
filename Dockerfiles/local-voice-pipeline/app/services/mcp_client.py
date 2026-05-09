"""Async MCP client using Streamable HTTP transport (spec 2024-11-05).

Connects to an MCP server, lists tools, and executes tool calls.
Designed for the voice pipeline: minimal overhead, no external MCP SDK dependency.
"""
import json
import logging
import ssl
import aiohttp
from typing import Callable

logger = logging.getLogger(__name__)

# Voice-relevant HA tools by default (small enough for a 1.7B model's context window)
DEFAULT_VOICE_TOOLS = [
    "ha_search_entities",   # find entities by name before controlling them
    "ha_get_state",         # check current state of an entity
    "ha_call_service",      # control devices (turn on/off, set brightness, etc.)
    "ha_bulk_control",      # control multiple devices at once
]


class MCPClient:
    """
    Minimal MCP Streamable HTTP client.

    Lifecycle:
        client = MCPClient(url)
        await client.connect()          # initialize session
        tools = await client.fetch_tools(names=[...])
        result = await client.call_tool("ha_call_service", {...})
        await client.close()
    """

    def __init__(self, server_url: str, verify_ssl: bool = False):
        self.server_url = server_url.rstrip("/")
        self._verify_ssl = verify_ssl
        self._session_id: str | None = None
        self._req_id = 0
        self._http: aiohttp.ClientSession | None = None
        self._tools: list[dict] = []

    async def connect(self) -> None:
        """Perform MCP initialize handshake and obtain a session ID."""
        ssl_context = ssl.create_default_context() if self._verify_ssl else False
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self._http = aiohttp.ClientSession(connector=connector)

        resp_data, headers = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "local-voice-pipeline", "version": "1.0"},
                },
            },
            include_session=False,
        )

        self._session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if not self._session_id:
            raise RuntimeError("MCP server did not return mcp-session-id header")

        server_info = resp_data.get("result", {}).get("serverInfo", {})
        logger.info(
            f"MCP session established with {server_info.get('name','?')} "
            f"v{server_info.get('version','?')} | session={self._session_id[:8]}..."
        )

    async def fetch_tools(self, names: list[str] | None = None) -> list[dict]:
        """Fetch tool list from the server, optionally filtering to a subset by name."""
        resp_data, _ = await self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}}
        )

        all_tools: list[dict] = resp_data["result"]["tools"]
        if names:
            name_set = set(names)
            all_tools = [t for t in all_tools if t["name"] in name_set]

        self._tools = all_tools
        logger.info(f"MCP tools loaded ({len(all_tools)}): {[t['name'] for t in all_tools]}")
        return all_tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool on the MCP server and return the text result.
        
        Automatically reconnects and retries once if the session has expired.
        """
        logger.info(f"MCP call: {name}({json.dumps(arguments)[:200]})")
        try:
            return await self._call_tool_once(name, arguments)
        except Exception as e:
            # Session likely expired — reconnect and retry once
            logger.warning(f"MCP call failed ({e}), reconnecting session and retrying...")
            try:
                await self._reconnect()
                return await self._call_tool_once(name, arguments)
            except Exception as e2:
                logger.error(f"MCP call failed after reconnect: {e2}")
                return f"Tool error: {e2}"

    async def _call_tool_once(self, name: str, arguments: dict) -> str:
        resp_data, _ = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )

        if "error" in resp_data:
            err = resp_data["error"]
            return f"Tool error {err.get('code')}: {err.get('message')}"

        result = resp_data.get("result", {})
        if result.get("isError"):
            return f"Tool error: {_extract_text(result.get('content', []))}"

        return _extract_text(result.get("content", []))

    async def _reconnect(self) -> None:
        """Re-initialize the MCP session (e.g. after server-side session expiry)."""
        if self._http:
            try:
                await self._http.close()
            except Exception:
                pass
        self._session_id = None
        ssl_context = ssl.create_default_context() if self._verify_ssl else False
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self._http = aiohttp.ClientSession(connector=connector)
        resp_data, headers = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "local-voice-pipeline", "version": "1.0"},
                },
            },
            include_session=False,
        )
        self._session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if not self._session_id:
            raise RuntimeError("MCP reconnect: server did not return mcp-session-id")
        logger.info(f"MCP session reconnected | session={self._session_id[:8]}...")

    def to_openai_tools(self) -> list[dict]:
        """Convert loaded MCP tool schemas to OpenAI function-calling format."""
        out = []
        for t in self._tools:
            schema = dict(t.get("inputSchema", {"type": "object", "properties": {}}))
            schema.pop("additionalProperties", None)
            # Simplify ha_call_service to remove optional params that confuse small models
            if t["name"] == "ha_call_service":
                schema = {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "enum": ["light", "switch", "climate", "cover", "media_player",
                                     "fan", "lock", "vacuum", "input_boolean", "homeassistant",
                                     "automation", "script"],
                            "description": "HA domain (one word, e.g. 'light' for light.office_light)",
                        },
                        "service": {
                            "type": "string",
                            "description": "Service name e.g. 'turn_on', 'turn_off', 'toggle'",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "Full entity ID from search results e.g. 'light.office_light'",
                        },
                        "wait": {"type": "boolean", "default": True},
                    },
                    "required": ["domain", "service"],
                }
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        # Truncate long descriptions to save tokens in the context window
                        "description": (t.get("description") or "")[:300],
                        "parameters": schema,
                    },
                }
            )
        return out

    def make_handler(self, tool_name: str) -> Callable:
        """Return a Pipecat-compatible async function handler for a given tool name."""

        async def handler(params) -> None:
            result = await self.call_tool(tool_name, params.arguments)
            await params.result_callback(result)

        handler.__name__ = tool_name
        return handler

    async def close(self) -> None:
        if self._http:
            await self._http.close()
            self._http = None

    # ── internal helpers ──────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _post(self, payload: dict, include_session: bool = True) -> tuple[dict, dict]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self._session_id:
            headers["mcp-session-id"] = self._session_id

        async with self._http.post(self.server_url, json=payload, headers=headers) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            # Use chunk iteration to handle chunked Transfer-Encoding and SSE robustly
            body_bytes = b""
            async for chunk in resp.content.iter_any():
                body_bytes += chunk
            body = body_bytes.decode("utf-8", errors="replace")

        content_type = resp_headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in body.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:]), resp_headers
            raise ValueError(f"No SSE data line in response: {body[:300]}")
        else:
            return json.loads(body), resp_headers


def _extract_text(content: list[dict]) -> str:
    """Concatenate text items from MCP content array."""
    parts = [item["text"] for item in content if item.get("type") == "text"]
    return "\n".join(parts) if parts else str(content)
