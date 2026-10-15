"""统一配置中心：LLM 厂商模板、MCP 服务器配置模型、应用级配置。

配置来源优先级：环境变量 / .env 文件 > 代码默认值。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()

Transport = Literal["stdio", "sse", "streamable-http"]
TRANSPORTS = ("stdio", "sse", "streamable-http")

# 三家 LLM 厂商的 OpenAI 兼容模板，可通过 LLM_MODEL / LLM_BASE_URL 覆盖
LLM_PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_env": "ZHIPU_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "你是由 mcp-agent 框架驱动的智能助手。你可以通过调用工具来帮助用户完成任务，"
    "工具可能来自多个外部业务系统（MCP Server）或框架内置工具。"
    "请在需要时主动选择合适的工具，并基于工具返回结果用中文简洁作答。"
)


@dataclass
class ServerConfig:
    """一个外部 MCP Server 的连接配置（可 JSON 持久化）。"""

    id: str
    name: str
    transport: Transport = "sse"
    # http / sse 传输
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # stdio 传输
    command: str | None = None
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    # 启动行为
    autostart: bool = False

    @classmethod
    def create(cls, data: dict[str, Any]) -> "ServerConfig":
        """从请求数据创建，自动生成唯一 ID。"""
        allowed = {f for f in cls.__dataclass_fields__ if f != "id"}
        payload = {k: v for k, v in (data or {}).items() if k in allowed}
        transport = payload.get("transport", "sse")
        if transport not in TRANSPORTS:
            raise ValueError(f"不支持的传输方式: {transport}")
        return cls(id=uuid.uuid4().hex[:8], **payload)

    def update(self, data: dict[str, Any]) -> None:
        for key, value in (data or {}).items():
            if key in self.__dataclass_fields__ and key != "id":
                setattr(self, key, value)
        if self.transport not in TRANSPORTS:
            raise ValueError(f"不支持的传输方式: {self.transport}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("服务器名称不能为空")
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio 传输必须提供 command")
        elif not self.url:
            raise ValueError(f"{self.transport} 传输必须提供 url")


@dataclass
class AppConfig:
    """应用级配置。"""

    data_dir: Path
    flask_host: str = "127.0.0.1"
    flask_port: int = 5000

    # LLM
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.7
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # 能力层（接口平台）
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    api_token: str = ""  # 接口平台 Bearer 鉴权（空则不鉴权）

    # 运行参数
    request_timeout: float = 30.0
    health_check_interval: float = 60.0
    autostart: bool = True

    @property
    def servers_file(self) -> Path:
        return self.data_dir / "mcp_servers.json"

    @property
    def tool_states_file(self) -> Path:
        return self.data_dir / "tool_states.json"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def digital_human_dir(self) -> Path:
        return self.data_dir / "digital_human"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def llm_ready(self) -> bool:
        """是否已配置可用的 LLM 凭证。"""
        return bool(self.llm_api_key)


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


_cached: AppConfig | None = None


def load_config() -> AppConfig:
    """从环境变量 / .env 加载配置（进程内缓存单例）。"""
    global _cached
    if _cached is not None:
        return _cached

    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    if provider not in LLM_PROVIDERS:
        provider = "deepseek"
    template = LLM_PROVIDERS[provider]

    data_dir = Path(os.getenv("MCP_AGENT_DATA_DIR", "./data")).expanduser().resolve()

    _cached = AppConfig(
        data_dir=data_dir,
        flask_host=os.getenv("FLASK_HOST", "127.0.0.1"),
        flask_port=int(os.getenv("FLASK_PORT", "5000")),
        llm_provider=provider,
        llm_api_key=os.getenv(template["key_env"], "").strip(),
        llm_model=os.getenv("LLM_MODEL", "").strip() or template["model"],
        llm_base_url=os.getenv("LLM_BASE_URL", "").strip() or template["base_url"],
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        request_timeout=float(os.getenv("MCP_AGENT_TIMEOUT", "30")),
        health_check_interval=float(os.getenv("MCP_AGENT_HEALTH_INTERVAL", "60")),
        autostart=_env_bool("MCP_AGENT_AUTOSTART", True),
        tts_voice=os.getenv("MCP_AGENT_TTS_VOICE", "").strip() or "zh-CN-XiaoxiaoNeural",
        api_token=os.getenv("MCP_AGENT_API_TOKEN", "").strip(),
    )
    _cached.ensure_dirs()
    return _cached
