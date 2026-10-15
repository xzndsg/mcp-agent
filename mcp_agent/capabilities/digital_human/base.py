"""数字人能力协议。"""
from __future__ import annotations

from typing import Any, Protocol


class DigitalHumanProvider(Protocol):
    """数字人 provider 协议：形象配置 + 驱动状态。"""

    name: str

    def available(self) -> bool: ...
    def metadata(self) -> dict[str, Any]: ...

    def get_config(self) -> dict[str, Any]:
        """形象与动画参数（含 image_url / speaking 状态）。"""
        ...

    def set_config(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def set_image(self, file_path: str) -> dict[str, Any]:
        """更换数字人形象图。"""
        ...

    def set_speaking(self, speaking: bool) -> None:
        """标记说话状态（供前端与接口平台读取）。"""
        ...
