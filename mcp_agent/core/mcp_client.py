"""MCP 客户端：统一封装 stdio / sse / streamable-http 三种传输。

设计要点：
- 每个连接在**独立线程 + 独立 asyncio 事件循环**中维持 MCP 的 async context，
  多台服务器互不影响，Flask / LangChain 侧可以用同步方法直接调用；
- 同步方法通过 ``run_coroutine_threadsafe`` 桥接到连接线程；
- stdio 子进程 stderr 落盘到 log_dir/stdio-<id>.log，连接秒退可诊断；
- 所有调用失败均转化为 ToolCallResult(success=False)，不把异常抛给 Agent。
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .config import ServerConfig
from .logging_utils import get_logger

logger = get_logger("mcp_client")


def _pick(obj: Any, *names: str, default: Any = None) -> Any:
    """兼容 mcp 1.x(camelCase) / 2.x(snake_case) 的字段取值。"""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_localhost(url: str | None) -> bool:
    """判断 URL 是否指向本机（本机代理会拦截 127.0.0.1，需绕过）。"""
    if not url:
        return False
    try:
        return (urlparse(url).hostname or "").lower() in _LOCAL_HOSTS
    except Exception:  # noqa: BLE001
        return False


@dataclass
class ToolCallResult:
    """工具调用的统一结果。"""

    success: bool
    text: str = ""
    error: str | None = None
    raw: Any = field(default=None, repr=False)


class McpClient:
    """与单个 MCP Server 的长连接。"""

    def __init__(
        self,
        config: ServerConfig,
        stdio_log_dir: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self._stdio_log_dir = stdio_log_dir

        # 运行时状态
        self.status: str = "offline"  # offline | connecting | online
        self.latency_ms: int = 0
        self.last_error: str | None = None
        self.connected_at: str | None = None

        # 线程 / 事件循环
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._stop_evt: asyncio.Event | None = None
        self._ready = threading.Event()
        self._stdio_errfile: Any = None
        self._http_client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ 生命周期

    def connect(self) -> bool:
        """建立连接并完成 MCP initialize 握手，返回是否成功。"""
        if self.status == "online":
            return True

        self.status = "connecting"
        self.last_error = None
        self._ready.clear()

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"mcp-{self.config.id}", daemon=True
        )
        self._thread.start()

        maintain_fut = asyncio.run_coroutine_threadsafe(self._maintain(), self._loop)
        maintain_fut.add_done_callback(self._on_maintain_done)

        if not self._ready.wait(timeout=self.timeout + 10):
            self.last_error = "连接超时"
            self.status = "offline"
            logger.warning("连接 MCP 服务器 %s 超时", self.config.name)
        return self.status == "online"

    def disconnect(self) -> None:
        """断开连接并停止后台事件循环。"""
        loop, thread = self._loop, self._thread
        if loop is not None and self._stop_evt is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._stop_evt.set(), loop).result(timeout=3)
            except Exception:
                pass
            # 给 context 退出留一点时间，然后停止事件循环
            loop.call_later(1.0, loop.stop)
        if thread is not None:
            thread.join(timeout=8)

        self._session = None
        self._loop = None
        self._thread = None
        self.status = "offline"
        if self._stdio_errfile is not None:
            try:
                self._stdio_errfile.close()
            except Exception:
                pass
            self._stdio_errfile = None
        logger.info("已断开 MCP 服务器 %s (%s)", self.config.name, self.config.id)

    @property
    def online(self) -> bool:
        return self.status == "online" and self._session is not None

    # ------------------------------------------------------------------ 内部实现

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _on_maintain_done(self, fut: asyncio.Future) -> None:
        try:
            fut.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - 仅记录，线程不能抛出
            logger.error("MCP 连接维护线程异常: %s", exc)

    def _open_stdio_log(self) -> Any:
        if self._stdio_log_dir is None:
            return None
        try:
            self._stdio_log_dir.mkdir(parents=True, exist_ok=True)
            path = self._stdio_log_dir / f"stdio-{self.config.id}.log"
            self._stdio_errfile = open(path, "a", encoding="utf-8")
            return self._stdio_errfile
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开 stdio 日志文件失败: %s", exc)
            return None

    async def _maintain(self) -> None:
        assert self._loop is not None
        self._stop_evt = asyncio.Event()
        started = time.time()

        transport = self.config.transport
        context: Any
        try:
            if transport == "stdio":
                env = dict(os.environ)
                env.update(self.config.env or {})
                params = StdioServerParameters(
                    command=self.config.command,
                    args=list(self.config.args or []),
                    cwd=self.config.cwd or None,
                    env=env,
                )
                context = stdio_client(params, errlog=self._open_stdio_log())
            elif transport == "sse":
                # localhost 绕过系统/环境代理，远程地址仍尊重代理配置
                bypass_proxy = _is_localhost(self.config.url)

                def _client_factory() -> httpx.AsyncClient:
                    return httpx.AsyncClient(trust_env=not bypass_proxy)

                context = sse_client(
                    self.config.url,
                    headers=self.config.headers or None,
                    httpx_client_factory=_client_factory,
                )
            else:  # streamable-http
                if _is_localhost(self.config.url):
                    self._http_client = httpx.AsyncClient(trust_env=False)
                context = streamable_http_client(
                    self.config.url,
                    http_client=self._http_client,
                )

            async with context as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    self._session = session
                    await session.initialize()

                    self.status = "online"
                    self.latency_ms = int((time.time() - started) * 1000)
                    self.connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.last_error = None
                    logger.info(
                        "已连接 MCP 服务器 %s (%s)，延迟 %sms",
                        self.config.name,
                        self.config.id,
                        self.latency_ms,
                    )
                    self._ready.set()

                    # 保持连接，直到 disconnect()
                    await self._stop_evt.wait()
        except Exception as exc:  # noqa: BLE001 - 任意连接失败都转为状态
            self.status = "offline"
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("连接 MCP 服务器 %s 失败: %s", self.config.name, self.last_error)
            self._ready.set()
        finally:
            self._session = None
            self.status = "offline"
            if self._http_client is not None:
                try:
                    await self._http_client.aclose()
                except Exception:  # noqa: BLE001
                    pass
                self._http_client = None

    def _submit(self, coro: Any, timeout: float | None = None) -> Any:
        if self._loop is None or not self._loop.is_running() or self._session is None:
            raise RuntimeError(f"服务器 {self.config.name} 当前未连接")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout or self.timeout)

    # ------------------------------------------------------------------ MCP 能力

    def list_tools(self) -> list[dict[str, Any]]:
        """返回 [{name, description, inputSchema}]。"""

        async def _do() -> list[dict[str, Any]]:
            result = await self._session.list_tools()  # type: ignore[union-attr]
            tools = getattr(result, "tools", result)
            return [
                {
                    "name": tool.name,
                    "description": _pick(tool, "description", default="") or "",
                    "inputSchema": dict(_pick(tool, "input_schema", "inputSchema", default={}) or {}),
                }
                for tool in tools
            ]

        return self._submit(_do())

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        """调用远程工具，任何失败都包装为 ToolCallResult。"""

        async def _do() -> Any:
            return await self._session.call_tool(name, arguments or {})  # type: ignore[union-attr]

        try:
            result = self._submit(_do())
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(success=False, error=f"{type(exc).__name__}: {exc}")
        return self._parse_call_result(result)

    def list_resources(self) -> list[dict[str, Any]]:
        """返回 [{uri, name, description, mimeType}]。"""

        async def _do() -> list[dict[str, Any]]:
            result = await self._session.list_resources()  # type: ignore[union-attr]
            resources = getattr(result, "resources", result)
            return [
                {
                    "uri": _pick(res, "uri", default=""),
                    "name": _pick(res, "name", default="") or "",
                    "description": _pick(res, "description", default="") or "",
                    "mimeType": _pick(res, "mime_type", "mimeType", default="") or "",
                }
                for res in resources
            ]

        return self._submit(_do())

    def read_resource(self, uri: str) -> str:
        """读取资源文本内容。"""

        async def _do() -> str:
            result = await self._session.read_resource(uri)  # type: ignore[union-attr]
            contents = getattr(result, "contents", [result])
            texts = []
            for item in contents:
                text = getattr(item, "text", None)
                if text is not None:
                    texts.append(text)
            return "\n".join(texts)

        return self._submit(_do())

    def ping(self) -> bool:
        """轻量探活。"""
        if not self.online:
            return False

        async def _do() -> None:
            send_ping = getattr(self._session, "send_ping", None)
            if send_ping is not None:
                await send_ping()

        try:
            self._submit(_do(), timeout=10)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("服务器 %s 探活失败: %s", self.config.name, exc)
            return False

    @staticmethod
    def _parse_call_result(result: Any) -> ToolCallResult:
        texts: list[str] = []
        for block in getattr(result, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                texts.append(getattr(block, "text", ""))
            elif block_type == "image":
                texts.append("[image content]")
            elif isinstance(block, str):
                texts.append(block)
            else:
                texts.append(str(block))

        is_error = bool(_pick(result, "is_error", "isError", default=False))
        text = "\n".join(texts)
        return ToolCallResult(
            success=not is_error,
            text=text,
            error=text if is_error else None,
            raw=result,
        )
