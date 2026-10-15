"""工具注册中心：跨 MCP Server 与进程内本地工具的统一聚合视图。

- 线程安全（ServerManager 后台健康检查与 Flask 请求线程会并发访问）；
- 每条工具带 available（连接是否在线）与 enabled（用户是否启用）两个状态；
- 维护一份"已启用且在线"的聚合缓存，供 Agent 构建工具列表。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

ToolEntry = dict[str, Any]

# 进程内本地工具使用的虚拟服务器 ID
LOCAL_SERVER_ID = "__local__"


class ToolRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # server_id -> {tool_name -> entry}
        self._tools: dict[str, dict[str, ToolEntry]] = {}
        self._enabled_cache: list[ToolEntry] = []
        self._cache_ts: float = 0.0

    # -------------------------------------------------------------- 内部工具

    @staticmethod
    def _clone(entry: ToolEntry) -> ToolEntry:
        clone = dict(entry)
        clone["inputSchema"] = dict(entry.get("inputSchema") or {})
        return clone

    def _rebuild_cache_locked(self) -> None:
        aggregated: dict[str, ToolEntry] = {}
        for server_tools in self._tools.values():
            for entry in server_tools.values():
                if not entry.get("available") or not entry.get("enabled", True):
                    continue
                old = aggregated.get(entry["name"])
                if old and old.get("updated_at", 0) >= entry.get("updated_at", 0):
                    continue
                aggregated[entry["name"]] = self._clone(entry)
        self._enabled_cache = sorted(aggregated.values(), key=lambda item: item["name"])
        self._cache_ts = time.time()

    # -------------------------------------------------------------- MCP 工具

    def set_server_tools(
        self,
        server_id: str,
        tools: Optional[list[dict[str, Any]]],
        enabled_lookup: Optional[Callable[[str], bool]] = None,
    ) -> None:
        """发布某台 MCP Server 的最新工具清单（连接成功 / 刷新时调用）。"""
        now = time.time()
        with self._lock:
            server_map = self._tools.setdefault(server_id, {})
            for entry in server_map.values():
                entry["available"] = False

            for raw in tools or []:
                name = str((raw or {}).get("name", "")).strip()
                if not name:
                    continue
                entry = server_map.get(
                    name,
                    {
                        "name": name,
                        "description": "",
                        "inputSchema": {},
                        "origin": "mcp",
                        "server_id": server_id,
                        "available": False,
                        "enabled": True,
                        "updated_at": 0.0,
                    },
                )
                entry["description"] = str(raw.get("description") or "")
                schema = raw.get("inputSchema")
                entry["inputSchema"] = dict(schema) if isinstance(schema, dict) else {}
                entry["origin"] = "mcp"
                entry["server_id"] = server_id
                entry["available"] = True
                entry["updated_at"] = now
                if enabled_lookup is not None:
                    try:
                        entry["enabled"] = bool(enabled_lookup(name))
                    except Exception:
                        entry.setdefault("enabled", True)
                else:
                    entry.setdefault("enabled", True)
                server_map[name] = entry

            self._rebuild_cache_locked()

    def mark_all_unavailable(self, server_id: str) -> None:
        with self._lock:
            for entry in self._tools.get(server_id, {}).values():
                entry["available"] = False
                entry["updated_at"] = time.time()
            self._rebuild_cache_locked()

    def remove_server(self, server_id: str) -> None:
        with self._lock:
            self._tools.pop(server_id, None)
            self._rebuild_cache_locked()

    # -------------------------------------------------------------- 本地工具

    def set_local_tools(self, entries: list[ToolEntry]) -> None:
        """全量同步进程内本地工具（始终 available，默认 enabled）。"""
        now = time.time()
        with self._lock:
            server_map: dict[str, ToolEntry] = {}
            for raw in entries or []:
                name = str((raw or {}).get("name", "")).strip()
                if not name:
                    continue
                server_map[name] = {
                    "name": name,
                    "description": str(raw.get("description") or ""),
                    "inputSchema": dict(raw.get("inputSchema") or {}),
                    "origin": "local",
                    "server_id": LOCAL_SERVER_ID,
                    "available": True,
                    "enabled": bool(raw.get("enabled", True)),
                    "updated_at": now,
                }
            self._tools[LOCAL_SERVER_ID] = server_map
            self._rebuild_cache_locked()

    # -------------------------------------------------------------- 状态与查询

    def set_enabled(self, server_id: str, tool_name: str, enabled: bool) -> None:
        with self._lock:
            entry = self._tools.get(server_id, {}).get(tool_name)
            if entry is None:
                return
            entry["enabled"] = bool(enabled)
            entry["updated_at"] = time.time()
            self._rebuild_cache_locked()

    def get_enabled(self, server_id: str, tool_name: str) -> bool:
        with self._lock:
            return self._tools.get(server_id, {}).get(tool_name, {}).get("enabled", True)

    def get_entry(self, server_id: str, tool_name: str) -> ToolEntry | None:
        with self._lock:
            entry = self._tools.get(server_id, {}).get(tool_name)
            return self._clone(entry) if entry else None

    def get_server_tools(
        self,
        server_id: str,
        include_disabled: bool = True,
        include_unavailable: bool = False,
    ) -> list[ToolEntry]:
        with self._lock:
            result = []
            for entry in self._tools.get(server_id, {}).values():
                if not include_unavailable and not entry.get("available"):
                    continue
                if not include_disabled and not entry.get("enabled", True):
                    continue
                result.append(self._clone(entry))
            result.sort(key=lambda item: item["name"])
            return result

    def get_enabled_tools(self) -> list[ToolEntry]:
        """返回所有已启用且在线的工具（Agent 实际可调用集合）。"""
        with self._lock:
            return [self._clone(entry) for entry in self._enabled_cache]

    def get_all_tools(self, include_disabled: bool = True) -> list[ToolEntry]:
        with self._lock:
            result = []
            for server_id, server_tools in self._tools.items():
                for entry in server_tools.values():
                    if not include_disabled and not entry.get("enabled", True):
                        continue
                    item = self._clone(entry)
                    result.append(item)
            result.sort(key=lambda item: (item["server_id"], item["name"]))
            return result

    def cache_timestamp(self) -> float:
        with self._lock:
            return self._cache_ts

    def reset(self) -> None:
        """仅供测试使用。"""
        with self._lock:
            self._tools.clear()
            self._enabled_cache.clear()
            self._cache_ts = 0.0
