import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Any

SESSION_TTL_SECONDS: int = 60 * 60 * 2

@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    # JSON Architecture Cache
    cached_layout: Optional[str] = None
    cached_data: Optional[dict] = None
    cached_query: Optional[str] = None
    cached_script: Optional[str] = None
    cached_schema: Optional[str] = None
    cache_version: int = 0
    
    dataset_df: Optional[Any] = None
    dataset_schema: Optional[str] = None

    def touch(self) -> None:
        self.last_active = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.touch()

    def cache_dashboard(self, layout: str, data: dict, query: str, script: Optional[str] = None, schema: Optional[str] = None) -> None:
        self.cached_layout = layout
        self.cached_data = data
        self.cached_query = query
        self.cached_script = script
        self.cached_schema = schema
        self.cache_version += 1
        self.touch()
        
    def update_data(self, new_data: dict) -> None:
        if self.cached_data is None:
            self.cached_data = {}
        self.cached_data.update(new_data)
        self.cache_version += 1
        self.touch()
        
    def set_dataset(self, df: Any, schema: str) -> None:
        self.dataset_df = df
        self.dataset_schema = schema
        self.touch()

    def has_cache(self) -> bool:
        return self.cached_layout is not None

    def clear_cache(self) -> None:
        self.cached_layout = None
        self.cached_data = None
        self.cached_query = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.id,
            "message_count": len(self.messages),
            "created_at": self.created_at,
            "last_active": self.last_active,
            "messages": self.messages,
            "has_cache": self.has_cache(),
            "cache_version": self.cache_version,
            "cached_query": self.cached_query,
            "cached_data": self.cached_data,
            "cached_layout": self.cached_layout,
            "has_dataset": self.dataset_df is not None,
            "dataset_schema": self.dataset_schema
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(id=session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            del self._sessions[session_id]
            return None
        return session

    def get_or_create(self, session_id: Optional[str]) -> tuple[Session, bool]:
        if session_id:
            session = self.get(session_id)
            if session:
                return session, False
        session = self.create()
        return session, True

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def reap_expired(self) -> int:
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def list_sessions(self) -> list[dict]:
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

store = SessionStore()
