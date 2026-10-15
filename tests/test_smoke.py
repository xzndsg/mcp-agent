"""Flask 应用冒烟测试：健康检查、演示模式对话、SSE、MCP 服务器配置 CRUD。"""
import pytest

from mcp_agent.app import create_app
from mcp_agent.core.config import AppConfig


@pytest.fixture()
def app(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    app = create_app(config, start_background=False)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["status"] == "up"


def test_chat_demo_mode(client):
    resp = client.post("/api/chat", json={"message": "你好"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["session_id"]
    assert "演示模式" in data["reply"]
    # 内置本地工具应出现在工具列表中
    assert "framework_info" in data["tools"]


def test_chat_validation(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 400


def test_chat_sse_stream(client):
    resp = client.get("/api/chat/stream?message=测试SSE")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    text = resp.get_data(as_text=True)
    assert "data:" in text
    assert '"type": "done"' in text
    assert "演示模式" in text


def test_server_crud(client):
    # 新增
    resp = client.post(
        "/api/servers",
        json={"name": "demo-http", "transport": "streamable-http", "url": "http://127.0.0.1:8100/mcp"},
    )
    assert resp.status_code == 200
    server_id = resp.get_json()["data"]["id"]

    # 列表
    servers = client.get("/api/servers").get_json()["data"]
    assert len(servers) == 1
    assert servers[0]["status"] == "offline"

    # 工具列表接口可用
    tools = client.get("/api/tools").get_json()["data"]
    assert any(t["name"] == "framework_info" for t in tools)

    # 删除
    assert client.delete(f"/api/servers/{server_id}").status_code == 200
    assert client.get("/api/servers").get_json()["data"] == []


def test_server_validation(client):
    resp = client.post(
        "/api/servers",
        json={"name": "bad", "transport": "streamable-http"},  # 缺 url
    )
    assert resp.status_code == 400
