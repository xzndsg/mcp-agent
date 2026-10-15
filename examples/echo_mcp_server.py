"""示例 MCP Server：提供 echo / add 两个工具。

用法：
    # stdio 传输（供 mcp-agent 以子进程方式接入）
    python examples/echo_mcp_server.py --transport stdio

    # Streamable HTTP 传输（在 mcp-agent 控制台以 URL 接入）
    python examples/echo_mcp_server.py --transport streamable-http --port 8100
    # 默认 URL 为 http://127.0.0.1:8100/mcp/

    # 旧版 SSE 传输
    python examples/echo_mcp_server.py --transport sse --port 8100
"""
from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("echo-demo")


@mcp.tool()
def echo(text: str) -> str:
    """原样返回输入的文本，用于链路连通性测试。"""
    return f"echo: {text}"


@mcp.tool()
def add(a: float, b: float) -> float:
    """计算两个数字的和。"""
    return a + b


@mcp.tool()
def server_time() -> str:
    """获取服务器当前时间。"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="mcp-agent 示例 MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # mcp 2.x：HTTP/SSE 传输通过关键字参数指定监听地址
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
