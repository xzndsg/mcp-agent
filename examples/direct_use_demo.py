"""作为库嵌入的演示：注册业务函数为本地工具并对话。

运行：
    python examples/direct_use_demo.py

未配置 LLM Key 时走本地演示模式；配置 .env 后由模型自动决策调用工具。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_agent.core.agent import AgentRuntime  # noqa: E402
from mcp_agent.core.config import load_config  # noqa: E402
from mcp_agent.core.local_tools import LocalToolKit  # noqa: E402
from mcp_agent.core.server_manager import ServerManager  # noqa: E402
from mcp_agent.core.tool_registry import ToolRegistry  # noqa: E402


def build_runtime() -> AgentRuntime:
    kit = LocalToolKit()

    @kit.register
    def query_order(order_id: str) -> str:
        """根据订单号查询订单的物流状态。"""
        # 这里替换成真实业务系统的 API / 数据库查询
        mock_db = {"A1001": "已发货，预计明天送达", "A1002": "已签收"}
        return mock_db.get(order_id, f"未找到订单 {order_id}")

    @kit.register(description="查询商品当前库存数量")
    def stock_count(sku: str) -> str:
        """查询商品当前库存数量。"""
        return f"商品 {sku} 当前库存 128 件"

    registry = ToolRegistry()
    registry.set_local_tools(kit.to_entries())
    # 完整构造会读取 data/mcp_servers.json；演示场景同样支持接入外部 MCP Server
    manager = ServerManager(
        config=load_config(),
        registry=registry,
        local_kit=kit,
    )
    return AgentRuntime(manager=manager, local_kit=kit, registry=registry)


def main() -> None:
    runtime = build_runtime()
    print("可用工具：", runtime.enabled_tool_names())
    result = runtime.chat("demo", "帮我查一下订单 A1001 到哪了")
    print("\n助手：")
    print(result["reply"])


if __name__ == "__main__":
    main()
