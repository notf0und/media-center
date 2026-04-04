import os, logging, aiohttp
from typing import Optional

logger = logging.getLogger(__name__)

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

HA_SYSTEM_PROMPT_SUFFIX = """
You have access to smart home controls via tool calls.
Use call_ha_service to control devices. Use get_ha_state to check device status.
Be direct and confirm what you did in one sentence.
"""

async def call_ha_service(domain: str, service: str, entity_id: Optional[str] = None, data: Optional[dict] = None) -> str:
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    payload = data or {}
    if entity_id:
        payload["entity_id"] = entity_id
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{HA_URL}/api/services/{domain}/{service}", json=payload, headers=headers) as resp:
            if resp.status < 300:
                return "Done."
            else:
                return f"Error {resp.status}: {await resp.text()}"

async def get_ha_state(entity_id: str) -> str:
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/api/states/{entity_id}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return f"{entity_id} is {data['state']}"
            else:
                return f"Error {resp.status}"

async def build_ha_tools() -> list:
    """Returns OpenAI tool definitions for HA control."""
    if not HA_TOKEN:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "call_ha_service",
                "description": "Control a Home Assistant smart home device or service",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "HA domain e.g. light, switch, media_player"},
                        "service": {"type": "string", "description": "HA service e.g. turn_on, turn_off, toggle"},
                        "entity_id": {"type": "string", "description": "Entity ID e.g. light.living_room"},
                        "data": {"type": "object", "description": "Additional service data e.g. {brightness: 150}"},
                    },
                    "required": ["domain", "service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_ha_state",
                "description": "Get the current state of a Home Assistant entity",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "description": "Entity ID to query"},
                    },
                    "required": ["entity_id"],
                },
            },
        },
    ]
