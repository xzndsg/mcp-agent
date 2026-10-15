"""ToolRegistry / LocalToolKit 单元测试。"""
from mcp_agent.core.local_tools import LocalToolKit
from mcp_agent.core.tool_registry import LOCAL_SERVER_ID, ToolRegistry


def _mcp_tools():
    return [
        {"name": "tool_a", "description": "A 工具", "inputSchema": {"type": "object"}},
        {"name": "tool_b", "description": "B 工具", "inputSchema": {}},
    ]


def test_server_tools_aggregate_and_disable():
    registry = ToolRegistry()
    registry.set_server_tools("srv1", _mcp_tools())

    enabled = {t["name"] for t in registry.get_enabled_tools()}
    assert enabled == {"tool_a", "tool_b"}

    registry.set_enabled("srv1", "tool_a", False)
    enabled = {t["name"] for t in registry.get_enabled_tools()}
    assert enabled == {"tool_b"}
    assert registry.get_enabled("srv1", "tool_a") is False


def test_mark_unavailable_removes_from_enabled_cache():
    registry = ToolRegistry()
    registry.set_server_tools("srv1", _mcp_tools())
    assert len(registry.get_enabled_tools()) == 2

    registry.mark_all_unavailable("srv1")
    assert registry.get_enabled_tools() == []
    # 重连发布时，enabled 由持久化状态决定（manager 总会传入 enabled_lookup）
    registry.set_server_tools("srv1", _mcp_tools(), enabled_lookup=lambda _name: False)
    assert registry.get_enabled_tools() == []  # 被持久化状态禁用
    registry.set_server_tools("srv1", _mcp_tools(), enabled_lookup=lambda _name: True)
    assert len(registry.get_enabled_tools()) == 2


def test_local_tools_always_available():
    kit = LocalToolKit()

    @kit.register
    def greet(name: str, times: int = 1) -> str:
        """打招呼。"""
        return ("hello " + name) * times

    entries = kit.to_entries()
    assert entries[0]["name"] == "greet"
    schema = entries[0]["inputSchema"]
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["times"]["type"] == "integer"
    assert schema["required"] == ["name"]

    registry = ToolRegistry()
    registry.set_local_tools(entries)
    assert {t["name"] for t in registry.get_enabled_tools()} == {"greet"}
    assert registry.get_entry(LOCAL_SERVER_ID, "greet")["origin"] == "local"

    assert kit.get("greet").invoke({"name": "mcp", "times": 2}) == "hello mcphello mcp"
