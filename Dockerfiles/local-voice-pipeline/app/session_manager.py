import asyncio, logging, time
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_activity = time.time()
        self.metadata: Dict[str, Any] = {}

    def touch(self):
        self.last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

class SessionManager:
    def __init__(self, timeout_seconds: int = 300):
        self._sessions: Dict[str, Session] = {}
        self._timeout = timeout_seconds
        self._cleanup_task = None

    def get_or_create(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
            logger.info(f"New session: {session_id}")
        session = self._sessions[session_id]
        session.touch()
        return session

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)

    async def start_cleanup(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            expired = [sid for sid, s in self._sessions.items() if s.idle_seconds > self._timeout]
            for sid in expired:
                logger.info(f"Session expired: {sid}")
                self.remove(sid)
