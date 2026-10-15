"""mcp-agent 统一启动入口。

用法：
    python main.py            # 启动 Web 控制台（对话 / 数字人 / 语音 / 接口平台）
    python main.py web        # 同上
    python main.py serve      # 启动自举 MCP Server（把框架能力暴露为 MCP 工具）
    python main.py demo       # 终端对话演示
    python main.py doctor     # 环境自检（依赖 / 配置 / 能力清单）
"""
from __future__ import annotations

import sys


def _banner() -> None:
    print("=" * 62)
    print(" mcp-agent — Flask 服务外壳 + LangChain 智能内核 + MCP 业务连接")
    print(" 能力：REST/SSE · WebSocket · 自举 MCP Server · TTS · 数字人 · 接口平台")
    print("=" * 62)


def doctor() -> None:
    """环境自检：依赖、LLM 配置、能力清单一目了然。"""
    from mcp_agent import __version__

    print("=" * 62)
    print(f" mcp-agent 环境自检（v{__version__}）")
    print("=" * 62)

    for module in ("flask", "langchain", "mcp", "edge_tts", "pydantic"):
        try:
            __import__(module)
            print(f"  [ok] {module}")
        except ImportError:
            print(f"  [缺失] {module}（pip install -e . 可补齐）")

    from mcp_agent.core.config import load_config
    cfg = load_config()
    print(f"  LLM: {cfg.llm_provider} / {cfg.llm_model}，Key {'已配置' if cfg.llm_ready else '未配置（演示模式）'}")
    print(f"  接口平台鉴权: {'已启用 Bearer Token' if cfg.api_token else '未启用'}")
    print(f"  数据目录: {cfg.data_dir}")

    from mcp_agent.server.context import build_container
    container = build_container()
    for cap in container.capabilities.describe():
        providers = "、".join(
            f"{p.get('title') or p['name']}({'可用' if p['available'] else '不可用'})"
            for p in cap["providers"]
        )
        print(f"  能力[{cap['key']}] {cap['title']}: {providers}")
    print("\n自检完成。运行 python main.py web 启动控制台。")


def main() -> None:
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "web"
    if command in ("web", "start"):
        sys.argv = ["mcp-agent", "start", *sys.argv[2:]]
    elif command == "serve":
        sys.argv = ["mcp-agent", "serve", *sys.argv[2:]]
    elif command == "demo":
        sys.argv = ["mcp-agent", "demo"]
    elif command == "doctor":
        return doctor()
    else:
        print(__doc__)
        sys.exit(1)

    _banner()
    from mcp_agent.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
