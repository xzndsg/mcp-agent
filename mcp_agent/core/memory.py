"""记忆扩展点。

短期对话记忆由 SessionManager 承担；跨会话的长期记忆 / RAG 在此预留协议，
业务方实现 Memory 接口后注入 AgentRuntime 即可（向量库、知识库等）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Memory(Protocol):
    """长期记忆协议。"""

    def recall(self, query: str, session_id: str, top_k: int = 3) -> list[str]:
        """根据当前问题检索相关历史片段。"""
        ...

    def remember(self, text: str, session_id: str, role: str = "user") -> None:
        """写入一条记忆。"""
        ...


class NullMemory:
    """默认空实现：不启用长期记忆。"""

    def recall(self, query: str, session_id: str, top_k: int = 3) -> list[str]:
        return []

    def remember(self, text: str, session_id: str, role: str = "user") -> None:
        return None
