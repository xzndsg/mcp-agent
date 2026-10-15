"""能力层基座：Provider 协议与能力注册表。

框架核心只依赖这里的抽象协议，具体厂商实现（edge-tts / 各语音·视频模型 /
数字人渲染器）以 Provider 插件形式注册进来，实现完全解耦：
新增一个能力 = 实现协议 + 注册一行，核心代码零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    """所有能力 provider 的最小协议。"""

    name: str

    def available(self) -> bool:
        """依赖 / 凭证是否就绪（未就绪的能力仅展示、不可调用）。"""
        ...

    def metadata(self) -> dict[str, Any]:
        """能力元信息，用于前端展示与接口平台能力发现。"""
        ...


@dataclass
class Capability:
    """一种平台能力（tts / asr / video / digital_human ...），可挂多个 provider。"""

    key: str
    title: str
    description: str
    providers: dict[str, "Provider"] = field(default_factory=dict)

    def register(self, provider: Provider) -> None:
        self.providers[provider.name] = provider

    def get(self, name: str | None = None) -> Provider | None:
        """取指定 provider；缺省时返回第一个可用的。"""
        if name:
            return self.providers.get(name)
        for provider in self.providers.values():
            if provider.available():
                return provider
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "providers": [
                {"name": p.name, "available": p.available(), **p.metadata()}
                for p in self.providers.values()
            ],
        }


class CapabilityRegistry:
    """平台能力注册表：接口平台与前端据此做能力发现。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def add(self, capability: Capability) -> Capability:
        self._capabilities[capability.key] = capability
        return capability

    def get(self, key: str) -> Capability | None:
        return self._capabilities.get(key)

    def describe(self) -> list[dict[str, Any]]:
        return [cap.describe() for cap in self._capabilities.values()]
