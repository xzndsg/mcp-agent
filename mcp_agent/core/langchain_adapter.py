"""MCP / 本地工具 → LangChain StructuredTool 适配器。

注意（Pydantic v2 兼容）：不要用 ``type()`` 动态继承 BaseTool 覆盖字段，
统一通过官方工厂 ``StructuredTool.from_function`` 创建工具。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model

from .local_tools import LocalToolKit
from .server_manager import ServerManager
from .tool_registry import LOCAL_SERVER_ID, ToolRegistry

_JSON_TO_PY: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def json_schema_to_pydantic(schema: dict[str, Any], model_name: str = "ToolArguments"):
    """把 MCP 工具的 JSON Schema 动态生成为 Pydantic v2 模型（支持基础类型）。"""
    properties = (schema or {}).get("properties", {})
    required = set((schema or {}).get("required", []))

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        json_type = prop_schema.get("type", "string")
        py_type = _JSON_TO_PY.get(json_type, str)
        description = prop_schema.get("description") or prop_schema.get("title") or prop_name

        if prop_name in required:
            default_value: Any = ...
        elif "default" in prop_schema:
            default_value = prop_schema["default"]
        else:
            # 可选参数：允许 None
            py_type = Optional[py_type]
            default_value = None

        fields[prop_name] = (py_type, Field(default=default_value, description=description))

    safe_name = re.sub(r"[^0-9a-zA-Z_]", "_", model_name)
    return create_model(f"Args_{safe_name}", **fields)


def _build_mcp_tool(entry: dict[str, Any], manager: ServerManager) -> BaseTool:
    server_id = entry["server_id"]
    tool_name = entry["name"]

    def _call(**kwargs: Any) -> str:
        result = manager.call_tool(server_id, tool_name, kwargs)
        # 错误也以文本形式回传给模型，便于其自我纠正，而不是中断整个 Agent
        if not result.success:
            return f"工具 {tool_name} 调用失败：{result.error}"
        return result.text or "(工具执行完成，无文本返回)"

    async def _acall(**kwargs: Any) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _call(**kwargs))

    return StructuredTool.from_function(
        func=_call,
        coroutine=_acall,
        name=tool_name,
        description=entry.get("description") or tool_name,
        args_schema=json_schema_to_pydantic(entry.get("inputSchema") or {}, tool_name),
    )


def _build_local_tool(entry: dict[str, Any], kit: LocalToolKit) -> BaseTool:
    local = kit.get(entry["name"])
    assert local is not None

    def _call(**kwargs: Any) -> str:
        try:
            return local.invoke(kwargs)
        except Exception as exc:  # noqa: BLE001
            return f"工具 {local.name} 执行失败：{type(exc).__name__}: {exc}"

    async def _acall(**kwargs: Any) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _call(**kwargs))

    return StructuredTool.from_function(
        func=_call,
        coroutine=_acall,
        name=local.name,
        description=local.description or local.name,
        args_schema=json_schema_to_pydantic(local.input_schema, local.name),
    )


def build_langchain_tools(
    registry: ToolRegistry,
    manager: ServerManager | None = None,
    local_kit: LocalToolKit | None = None,
) -> list[BaseTool]:
    """把注册中心中"已启用且在线"的工具全部转换为 LangChain 工具。"""
    tools: list[BaseTool] = []
    for entry in registry.get_enabled_tools():
        try:
            if entry["origin"] == "local":
                if local_kit is not None:
                    tools.append(_build_local_tool(entry, local_kit))
            elif manager is not None:
                tools.append(_build_mcp_tool(entry, manager))
        except Exception:  # noqa: BLE001 - 单个工具构建失败不影响整体
            continue
    return tools
