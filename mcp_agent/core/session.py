"""多用户会话管理：按 session_id 隔离对话历史。"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage

DEFAULT_MAX_HISTORY = 20  # 注入 Prompt 的最近消息条数


@dataclass
class Session:
    session_id: str
    created_at: float = field(default_factory=time.time)
    history: list[BaseMessage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def recent_history(self, limit: int = DEFAULT_MAX_HISTORY) -> list[BaseMessage]:
        if limit <= 0:
            return list(self.history)
        return self.history[-limit:]

    def append(self, message: BaseMessage) -> None:
        self.history.append(message)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    def get_or_create(self, session_id: str | None = None) -> Session:
        sid = session_id or self.new_id()
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                session = Session(session_id=sid)
                self._sessions[sid] = session
            return session

    def clear(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            return session is not None

    def stats(self) -> dict:
        with self._lock:
            return {"session_count": len(self._sessions)}
