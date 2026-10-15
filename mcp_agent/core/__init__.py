"""core 包：纯 Python 内核，不依赖 Flask，可单独作为库嵌入。"""

from .config import AppConfig, ServerConfig, load_config
from .local_tools import LocalToolKit
from .tool_registry import ToolRegistry
from .mcp_client import McpClient, ToolCallResult
from .server_manager import ServerManager
from .session import Session, SessionManager
from .agent import AgentRuntime

__all__ = [
    "AppConfig",
    "ServerConfig",
    "load_config",
    "LocalToolKit",
    "ToolRegistry",
    "McpClient",
    "ToolCallResult",
    "ServerManager",
    "Session",
    "SessionManager",
    "AgentRuntime",
]
