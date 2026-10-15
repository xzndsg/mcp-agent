"""视频生成能力协议（数字人视频 / 文生视频等）。"""
from __future__ import annotations

from typing import Any, Protocol


class VideoProvider(Protocol):
    """视频生成 provider 协议：提交生成任务并查询结果。"""

    name: str

    def available(self) -> bool: ...
    def metadata(self) -> dict[str, Any]: ...

    def generate(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """提交生成任务，返回 {task_id, status, ...}。"""
        ...
