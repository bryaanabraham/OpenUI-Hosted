"""
Session store — in-memory conversation history keyed by session_id.

Each session holds an ordered list of OpenAI-format message dicts:
  [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

Sessions expire after SESSION_TTL_SECONDS of inactivity (default 2 hours).
The background reaper task cleans up expired sessions every 10 minutes.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Expire sessions after 2 hours of inactivity
SESSION_TTL_SECONDS: int = 60 * 60 * 2


@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_active = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.touch()

    def to_dict(self) -> dict:
        return {
            "session_id": self.id,
            "message_count": len(self.messages),
            "created_at": self.created_at,
            "last_active": self.last_active,
            "messages": self.messages,
        }


class SessionStore:
    """Thread-safe (asyncio-safe) in-memory session store."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create(self) -> Session:
        """Create a new empty session and return it."""
        session_id = str(uuid.uuid4())
        session = Session(id=session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Return the session if it exists and hasn't expired."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            del self._sessions[session_id]
            return None
        return session

    def get_or_create(self, session_id: Optional[str]) -> tuple[Session, bool]:
        """
        Return (session, is_new).

        If session_id is None or not found, create a fresh session.
        """
        if session_id:
            session = self.get(session_id)
            if session:
                return session, False
        session = self.create()
        return session, True

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        return self._sessions.pop(session_id, None) is not None

    def reap_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def list_sessions(self) -> list[dict]:
        """Return summary info for all active sessions."""
        self.reap_expired()
        return [
            {
                "session_id": s.id,
                "message_count": len(s.messages),
                "created_at": s.created_at,
                "last_active": s.last_active,
            }
            for s in self._sessions.values()
        ]


# Singleton store — shared across all requests in the process lifetime
store = SessionStore()
