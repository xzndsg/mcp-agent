"""自举 MCP Server：把本框架的 Agent 能力反向暴露为 MCP 工具。

通过 ``mcp-agent serve`` 启动后，Claude Desktop 等 MCP 宿主即可把本框架
当作一个 MCP Server 接入，间接使用其管理的所有业务工具。
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import __version__
from .context import Container


def build_mcp_server(container: Container) -> MCPServer:
    mcp = MCPServer("mcp-agent")

    @mcp.tool()
    def chat(message: str, session_id: str = "mcp-host") -> str:
        """与 mcp-agent 智能助手对话，助手会自动决策调用其接入的业务系统工具。

        Args:
            message: 用户的问题或指令。
            session_id: 会话 ID，同一 ID 可保持多轮上下文，默认使用公共会话。
        """
        return container.runtime.chat(session_id, message)["reply"]

    @mcp.tool()
    def list_available_tools() -> list[str]:
        """列出助手当前可调用的全部工具名称（来自已连接的 MCP Server 与本地工具）。"""
        return container.runtime.enabled_tool_names()

    @mcp.tool()
    def framework_info() -> str:
        """查看 mcp-agent 框架版本与当前运行状态。"""
        cfg = container.config
        servers = container.manager.list_servers()
        online = sum(1 for item in servers if item["status"] == "online")
        return (
            f"mcp-agent v{__version__}，LLM 厂商={cfg.llm_provider}，"
            f"模型={cfg.llm_model}，模型就绪={'是' if cfg.llm_ready else '否'}，"
            f"MCP 服务器在线 {online}/{len(servers)} 台。"
        )

    return mcp
