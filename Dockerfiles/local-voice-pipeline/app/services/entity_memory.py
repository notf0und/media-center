#!/usr/bin/env python3
"""Persistent entity memory — caches entity_id → friendly_name discovered via ha_search_entities.

After the first search for a device, subsequent requests skip the search entirely,
saving one full LLM round-trip (~4-12s) per known entity.
"""
import json, logging, os

logger = logging.getLogger(__name__)

MEMORY_FILE = os.environ.get("ENTITY_MEMORY_FILE", "/data/entity_memory.json")


class EntityMemory:
    def __init__(self, memory_file: str = MEMORY_FILE):
        self._file = memory_file
        self._data: dict[str, str] = self._load()   # {entity_id: friendly_name}
        self._base_prompt: str = ""

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(self._file) as f:
                data = json.load(f)
                logger.info(f"EntityMemory: loaded {len(data)} entities from {self._file}")
                return data
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning(f"EntityMemory: failed to load {self._file}: {e}")
            return {}

    def _flush(self):
        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            with open(self._file, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.warning(f"EntityMemory: failed to write {self._file}: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def add_from_search_results(self, results: list) -> int:
        """Ingest ha_search_entities result items. Returns count of newly added entries."""
        added = 0
        for r in results:
            eid = r.get("entity_id", "")
            name = r.get("friendly_name", "")
            if eid and name and eid not in self._data:
                self._data[eid] = name
                added += 1
        if added:
            self._flush()
            logger.info(f"EntityMemory: saved {added} new entities ({len(self._data)} total)")
        return added

    def set_base_prompt(self, content: str):
        """Store the base system prompt so memory can be appended to it on inject."""
        self._base_prompt = content

    def inject_into_context(self, context) -> bool:
        """Rewrite the system message in context to include current entity memory.
        Returns True if the message was updated."""
        if not self._data or not self._base_prompt:
            return False
        sys_msg = next((m for m in context.messages if m.get("role") == "system"), None)
        if not sys_msg:
            return False
        sys_msg["content"] = self._base_prompt + self._hint()
        return True

    def __len__(self):
        return len(self._data)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _hint(self) -> str:
        if not self._data:
            return ""
        lines = "\n".join(f"  {eid} ({name})" for eid, name in self._data.items())
        return f"\n\nKnown entities (call ha_call_service directly, no search needed):\n{lines}"
