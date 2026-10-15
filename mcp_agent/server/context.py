"""运行时容器：在 Flask 应用工厂中组装一次，各蓝图共享。"""
from __future__ import annotations

from dataclasses import dataclass

from flask import current_app

from .. import __version__
from ..capabilities import (
    Capability,
    CapabilityRegistry,
    EdgeTTSProvider,
    StaticImageHumanProvider,
    StubVideoProvider,
)
from ..core.agent import AgentRuntime
from ..core.config import AppConfig, load_config
from ..core.local_tools import LocalToolKit
from ..core.logging_utils import setup_logging
from ..core.server_manager import ServerManager
from ..core.tool_registry import ToolRegistry

_EXTENSION_KEY = "mcp_agent"


@dataclass
class Container:
    config: AppConfig
    registry: ToolRegistry
    kit: LocalToolKit
    manager: ServerManager
    runtime: AgentRuntime
    capabilities: CapabilityRegistry


def _build_capabilities(config: AppConfig) -> CapabilityRegistry:
    """注册平台多模态能力（解耦：增删 provider 只改这里，核心零改动）。"""
    caps = CapabilityRegistry()

    tts_cap = caps.add(Capability(
        key="tts",
        title="语音合成（TTS）",
        description="文本转语音，供数字人口播、语音回复与接口平台调用",
    ))
    tts_cap.register(EdgeTTSProvider(default_voice=config.tts_voice))

    caps.add(Capability(
        key="video",
        title="视频生成",
        description="预留视频模型接入位（即梦 / 可灵 / Runway / 本地渲染）",
    )).register(StubVideoProvider())

    caps.add(Capability(
        key="digital_human",
        title="数字人",
        description="静态图片驱动的口播数字人（CSS 动画 + 音频振幅，零 GPU）",
    )).register(StaticImageHumanProvider(config.data_dir))

    return caps


def build_container(config: AppConfig | None = None) -> Container:
    """组装内核（Flask 与自举 MCP Server 共用），并注册一个开箱即用的内置工具。"""
    config = config or load_config()
    config.ensure_dirs()
    setup_logging(config.log_dir)

    registry = ToolRegistry()
    kit = LocalToolKit()

    @kit.register
    def framework_info() -> str:
        """查看 mcp-agent 框架版本与运行状态。"""
        return f"mcp-agent v{__version__} 正在运行，当前未接入额外业务工具。"

    manager = ServerManager(config, registry, kit)
    runtime = AgentRuntime(
        config=config, manager=manager, local_kit=kit, registry=registry
    )
    return Container(
        config=config,
        registry=registry,
        kit=kit,
        manager=manager,
        runtime=runtime,
        capabilities=_build_capabilities(config),
    )


def get_container() -> Container:
    """在请求 / WebSocket 上下文中获取运行时容器。"""
    return current_app.extensions[_EXTENSION_KEY]
