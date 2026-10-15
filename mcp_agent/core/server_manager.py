"""多 MCP Server 生命周期管理。

职责：
- 服务器配置 CRUD 与 JSON 持久化（data/mcp_servers.json）；
- 工具启用状态持久化（data/tool_states.json）；
- 连接 / 断开，连接成功后把工具清单同步到 ToolRegistry；
- 后台定时健康检查，自动重连 autostart 的掉线服务器。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .config import AppConfig, ServerConfig
from .local_tools import LocalToolKit
from .logging_utils import get_logger
from .mcp_client import McpClient, ToolCallResult
from .tool_registry import LOCAL_SERVER_ID, ToolRegistry

logger = get_logger("server_manager")


class ServerManager:
    def __init__(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        local_kit: LocalToolKit | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.local_kit = local_kit

        self._lock = threading.RLock()
        self._configs: dict[str, ServerConfig] = {}
        self._clients: dict[str, McpClient] = {}
        # server_id -> {tool_name -> enabled}
        self._enabled_states: dict[str, dict[str, bool]] = {}

        self._health_stop = threading.Event()
        self._health_thread: threading.Thread | None = None

        self._load()
        if local_kit is not None:
            self.registry.set_local_tools(local_kit.to_entries())

    # ============================================================== 持久化

    def _load(self) -> None:
        # 服务器配置
        try:
            if self.config.servers_file.exists():
                raw = json.loads(self.config.servers_file.read_text(encoding="utf-8"))
                for item in raw:
                    cfg = ServerConfig(**{k: v for k, v in item.items() if k in ServerConfig.__dataclass_fields__})
                    self._configs[cfg.id] = cfg
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载 MCP 服务器配置失败: %s", exc)

        # 工具启用状态
        try:
            if self.config.tool_states_file.exists():
                self._enabled_states = json.loads(
                    self.config.tool_states_file.read_text(encoding="utf-8")
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载工具状态失败: %s", exc)
            self._enabled_states = {}

    def _save_servers(self) -> None:
        data = [cfg.to_dict() for cfg in self._configs.values()]
        self._write_json(self.config.servers_file, data)

    def _save_tool_states(self) -> None:
        self._write_json(self.config.tool_states_file, self._enabled_states)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ============================================================== 配置 CRUD

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._server_view(cfg.id) for cfg in self._configs.values()]

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._server_view(server_id) if server_id in self._configs else None

    def _server_view(self, server_id: str) -> dict[str, Any]:
        cfg = self._configs[server_id]
        client = self._clients.get(server_id)
        view = cfg.to_dict()
        if client is not None:
            view.update(
                status=client.status,
                latency_ms=client.latency_ms,
                last_error=client.last_error,
                connected_at=client.connected_at,
            )
        else:
            view.update(status="offline", latency_ms=0, last_error=None, connected_at=None)
        view["tool_count"] = len(
            self.registry.get_server_tools(server_id, include_disabled=False)
        )
        return view

    def add_server(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = ServerConfig.create(data)
        cfg.validate()
        with self._lock:
            if any(item.name == cfg.name for item in self._configs.values()):
                raise ValueError(f"已存在同名服务器: {cfg.name}")
            self._configs[cfg.id] = cfg
            self._save_servers()
            return self._server_view(cfg.id)

    def update_server(self, server_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cfg = self._configs.get(server_id)
            if cfg is None:
                raise KeyError(f"服务器不存在: {server_id}")
            cfg.update(data)
            cfg.validate()
            self._save_servers()
            return self._server_view(server_id)

    def remove_server(self, server_id: str) -> None:
        with self._lock:
            if server_id not in self._configs:
                raise KeyError(f"服务器不存在: {server_id}")
            self._disconnect_locked(server_id)
            del self._configs[server_id]
            self._enabled_states.pop(server_id, None)
            self.registry.remove_server(server_id)
            self._save_servers()
            self._save_tool_states()

    # ============================================================== 连接管理

    def connect(self, server_id: str) -> bool:
        with self._lock:
            cfg = self._configs.get(server_id)
            if cfg is None:
                raise KeyError(f"服务器不存在: {server_id}")

            self._disconnect_locked(server_id)
            client = McpClient(
                cfg,
                stdio_log_dir=self.config.log_dir,
                timeout=self.config.request_timeout,
            )
            success = client.connect()
            if success:
                self._clients[server_id] = client
                try:
                    tools = client.list_tools()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("获取服务器 %s 工具列表失败: %s", cfg.name, exc)
                    tools = []
                self.registry.set_server_tools(
                    server_id,
                    tools,
                    enabled_lookup=lambda name, sid=server_id: self._is_enabled(sid, name),
                )
            else:
                self.registry.set_server_tools(server_id, [])
            self._save_servers()
            return success

    def disconnect(self, server_id: str) -> None:
        with self._lock:
            if server_id not in self._configs:
                raise KeyError(f"服务器不存在: {server_id}")
            self._disconnect_locked(server_id)
            self.registry.mark_all_unavailable(server_id)

    def _disconnect_locked(self, server_id: str) -> None:
        client = self._clients.pop(server_id, None)
        if client is not None:
            try:
                client.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.warning("断开服务器 %s 时出错: %s", server_id, exc)

    def autostart_all(self) -> None:
        """连接所有标记 autostart 的服务器（建议在守护线程中调用）。"""
        with self._lock:
            targets = [cfg.id for cfg in self._configs.values() if cfg.autostart]
        for server_id in targets:
            try:
                self.connect(server_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("自动连接服务器 %s 失败: %s", server_id, exc)

    def get_client(self, server_id: str) -> McpClient | None:
        return self._clients.get(server_id)

    # ============================================================== 工具调用 / 状态

    def _is_enabled(self, server_id: str, tool_name: str) -> bool:
        return self._enabled_states.get(server_id, {}).get(tool_name, True)

    def set_tool_enabled(self, server_id: str, tool_name: str, enabled: bool) -> None:
        if server_id == LOCAL_SERVER_ID and self.local_kit is not None:
            # 本地工具的启停直接落在注册中心
            self.registry.set_enabled(server_id, tool_name, enabled)
            return
        if self.registry.get_entry(server_id, tool_name) is None:
            raise KeyError(f"工具不存在: {server_id}/{tool_name}")
        self.registry.set_enabled(server_id, tool_name, enabled)
        self._enabled_states.setdefault(server_id, {})[tool_name] = bool(enabled)
        self._save_tool_states()

    def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        if not self._is_enabled(server_id, tool_name):
            return ToolCallResult(success=False, error=f"工具 {tool_name} 已被禁用")
        if server_id == LOCAL_SERVER_ID:
            if self.local_kit is None:
                return ToolCallResult(success=False, error="本地工具集未初始化")
            tool = self.local_kit.get(tool_name)
            if tool is None:
                return ToolCallResult(success=False, error=f"本地工具不存在: {tool_name}")
            try:
                return ToolCallResult(success=True, text=tool.invoke(arguments or {}))
            except Exception as exc:  # noqa: BLE001
                return ToolCallResult(success=False, error=f"{type(exc).__name__}: {exc}")

        client = self._clients.get(server_id)
        if client is None or not client.online:
            return ToolCallResult(success=False, error="服务器未连接")
        return client.call_tool(tool_name, arguments)

    def list_resources(self, server_id: str) -> list[dict[str, Any]]:
        client = self._clients.get(server_id)
        if client is None or not client.online:
            return []
        return client.list_resources()

    # ============================================================== 健康检查

    def start_health_check(self) -> None:
        if self._health_thread is not None:
            return
        self._health_thread = threading.Thread(
            target=self._health_loop, name="mcp-health-check", daemon=True
        )
        self._health_thread.start()

    def _health_loop(self) -> None:
        interval = max(10.0, self.config.health_check_interval)
        while not self._health_stop.wait(interval):
            with self._lock:
                ids = list(self._configs.keys())
            for server_id in ids:
                client = self._clients.get(server_id)
                cfg = self._configs.get(server_id)
                try:
                    if client is not None and client.online:
                        if not client.ping():
                            logger.info("服务器 %s 探活失败，标记离线", cfg.name if cfg else server_id)
                            self.registry.mark_all_unavailable(server_id)
                            self._disconnect_locked(server_id)
                            if cfg and cfg.autostart:
                                self.connect(server_id)
                    elif cfg is not None and cfg.autostart:
                        self.connect(server_id)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("健康检查异常 %s: %s", server_id, exc)

    def shutdown(self) -> None:
        self._health_stop.set()
        with self._lock:
            for server_id in list(self._clients.keys()):
                self._disconnect_locked(server_id)
        logger.info("ServerManager 已关闭")
