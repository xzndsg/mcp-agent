"""视频生成占位 provider：未接入真实厂商时保持能力发现可见。"""
from __future__ import annotations

from typing import Any


class StubVideoProvider:
    """扩展位：接入即梦 / 可灵 / Runway / 本地 SadTalker 渲染时，
    实现 VideoProvider 协议并注册即可，核心代码零改动。"""

    name = "stub"

    def available(self) -> bool:
        return False

    def metadata(self) -> dict[str, Any]:
        return {
            "title": "视频模型（未接入）",
            "vendor": "-",
            "hint": "实现 VideoProvider 协议并注册即可启用",
        }

    def generate(self, prompt: str, image_path: str | None = None, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("视频生成 provider 未接入：请实现 VideoProvider 并注册")
