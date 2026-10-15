"""进程内本地工具：把普通 Python 函数直接注册为工具。

不经过 MCP 协议与子进程，作为：
1. 最简扩展方式（业务函数一行装饰器接入 Agent）；
2. stdio / HTTP 传输不稳定时的演示兜底链路。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

# Python 类型 -> JSON Schema 类型
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _py_type_to_json(annotation: Any) -> str:
    if annotation in (inspect.Parameter.empty, None):
        return "string"
    origin = getattr(annotation, "__origin__", None)
    if origin in (list, tuple):
        return "array"
    if origin in (dict,):
        return "object"
    return _TYPE_MAP.get(annotation, "string")


def build_schema_from_function(func: Callable[..., Any]) -> dict[str, Any]:
    """从函数签名与类型注解生成 MCP 风格的 JSON Schema（支持基础类型）。"""
    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        properties[param_name] = {
            "type": _py_type_to_json(param.annotation),
            "title": param_name,
        }
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            properties[param_name]["default"] = param.default

    return {"type": "object", "properties": properties, "required": required}


@dataclass
class LocalTool:
    name: str
    description: str
    func: Callable[..., Any]
    input_schema: dict[str, Any]

    def invoke(self, arguments: dict[str, Any]) -> str:
        result = self.func(**(arguments or {}))
        return result if isinstance(result, str) else str(result)


class LocalToolKit:
    """本地工具集合，线程安全注册/读取。"""

    def __init__(self) -> None:
        self._tools: dict[str, LocalTool] = {}

    def register(
        self,
        func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Any:
        """装饰器：支持 ``@kit.register`` 与 ``@kit.register(name=...)`` 两种写法。"""

        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            doc = inspect.getdoc(fn)
            first_doc_line = doc.strip().splitlines()[0] if doc else ""
            tool_desc = description or first_doc_line
            self._tools[tool_name] = LocalTool(
                name=tool_name,
                description=tool_desc,
                func=fn,
                input_schema=build_schema_from_function(fn),
            )
            return fn

        return wrap(func) if func is not None else wrap

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> LocalTool | None:
        return self._tools.get(name)

    def all(self) -> list[LocalTool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def to_entries(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self.all()
        ]
