"""MCP 管理接口：

- GET    /api/servers                  服务器列表（含状态）
- POST   /api/servers                  新增服务器
- PUT    /api/servers/<id>             更新服务器配置
- DELETE /api/servers/<id>             删除服务器
- POST   /api/servers/<id>/connect     连接
- POST   /api/servers/<id>/disconnect  断开
- GET    /api/servers/<id>/resources   资源列表
- GET    /api/tools                    工具列表（可按 server_id 过滤）
- POST   /api/tools/enable             启用 / 禁用工具
"""
from __future__ import annotations

from flask import Blueprint, request

from .context import get_container
from .responses import fail, ok

bp = Blueprint("mcp_admin", __name__)


@bp.get("/api/servers")
def list_servers():
    return ok(get_container().manager.list_servers())


@bp.post("/api/servers")
def add_server():
    data = request.get_json(silent=True) or {}
    view = get_container().manager.add_server(data)
    return ok(view, message="创建成功")


@bp.put("/api/servers/<server_id>")
def update_server(server_id: str):
    data = request.get_json(silent=True) or {}
    view = get_container().manager.update_server(server_id, data)
    return ok(view, message="更新成功")


@bp.delete("/api/servers/<server_id>")
def delete_server(server_id: str):
    get_container().manager.remove_server(server_id)
    return ok(message="已删除")


@bp.post("/api/servers/<server_id>/connect")
def connect_server(server_id: str):
    manager = get_container().manager
    success = manager.connect(server_id)
    if not success:
        view = manager.get_server(server_id)
        return fail(
            f"连接失败: {view.get('last_error') if view else '服务器不存在'}",
            http_status=502,
        )
    return ok(manager.get_server(server_id), message="连接成功")


@bp.post("/api/servers/<server_id>/disconnect")
def disconnect_server(server_id: str):
    get_container().manager.disconnect(server_id)
    return ok(get_container().manager.get_server(server_id), message="已断开")


@bp.get("/api/servers/<server_id>/resources")
def list_resources(server_id: str):
    return ok(get_container().manager.list_resources(server_id))


@bp.get("/api/tools")
def list_tools():
    manager = get_container().manager
    server_id = request.args.get("server_id")
    if server_id:
        return ok(manager.registry.get_server_tools(server_id))
    return ok(manager.registry.get_all_tools())


@bp.post("/api/tools/enable")
def toggle_tool():
    data = request.get_json(silent=True) or {}
    server_id = data.get("server_id")
    tool_name = data.get("name")
    enabled = data.get("enabled")
    if not server_id or not tool_name or not isinstance(enabled, bool):
        return fail("参数需要 server_id、name、enabled(bool)")
    get_container().manager.set_tool_enabled(server_id, tool_name, enabled)
    return ok(message="状态已更新")
