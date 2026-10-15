"""mcp-agent 命令行入口。

子命令：
    start   启动 Flask 服务（REST / SSE / WebSocket / 控制台）
    serve   启动自举 MCP Server（stdio / sse / streamable-http）
    demo    终端对话演示
"""
from __future__ import annotations

import argparse

from .core.config import load_config
from .core.logging_utils import get_logger

logger = get_logger("cli")


def cmd_start(args: argparse.Namespace) -> None:
    from .app import create_app

    config = load_config()
    app = create_app(config)
    host = args.host or config.flask_host
    port = args.port or config.flask_port
    logger.info("mcp-agent 控制台：http://%s:%s", host, port)
    # 关闭 reloader，避免后台连接 / 健康检查线程被重复启动
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def cmd_serve(args: argparse.Namespace) -> None:
    from .server.context import build_container
    from .server.mcp_host import build_mcp_server

    container = build_container()
    if container.config.autostart:
        container.manager.autostart_all()
    mcp = build_mcp_server(container)
    logger.info(
        "自举 MCP Server 启动：transport=%s，可用工具 %d 个",
        args.transport,
        len(container.runtime.enabled_tool_names()),
    )
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


def cmd_demo(args: argparse.Namespace) -> None:
    from .server.context import build_container

    container = build_container()
    runtime = container.runtime
    print("=" * 60)
    print("mcp-agent 终端演示（输入 exit / quit 退出）")
    print(f"LLM 就绪：{runtime.llm_ready}；可用工具：{runtime.enabled_tool_names()}")
    print("=" * 60)
    session_id = "cli-demo"
    while True:
        try:
            message = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message.lower() in ("exit", "quit"):
            break
        result = runtime.chat(session_id, message)
        print(f"\n助手：{result['reply']}")
    container.manager.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-agent", description="通用 MCP Agent 框架")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="启动 Flask 服务")
    p_start.add_argument("--host")
    p_start.add_argument("--port", type=int)
    p_start.set_defaults(func=cmd_start)

    p_serve = sub.add_parser("serve", help="启动自举 MCP Server")
    p_serve.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8200)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="终端对话演示")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
