"""二期能力层与接口平台测试：能力发现、TTS、数字人、OpenAI 兼容端点、鉴权。"""
import io

import pytest

from mcp_agent.app import create_app
from mcp_agent.core.config import AppConfig


@pytest.fixture()
def app(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    config.ensure_dirs()
    return create_app(config, start_background=False)


@pytest.fixture()
def client(app):
    app.testing = True
    return app.test_client()


def _container(app):
    return app.extensions["mcp_agent"]


class FakeTTSProvider:
    """本地假 TTS：不联网，返回可识别字节。"""

    name = "fake-tts"

    def available(self):
        return True

    def metadata(self):
        return {"title": "Fake TTS"}

    def voices(self):
        return [{"id": "v1", "label": "音色一"}]

    def synthesize(self, text, voice=None, rate=None):
        return b"fake-mp3:" + text.encode("utf-8")


def test_capabilities_describe(app):
    caps = _container(app).capabilities.describe()
    keys = {c["key"] for c in caps}
    assert {"tts", "video", "digital_human"} <= keys
    # edge-tts 已安装，应可用
    tts = next(c for c in caps if c["key"] == "tts")
    edge = next(p for p in tts["providers"] if p["name"] == "edge-tts")
    assert edge["available"] is True


def test_tts_endpoint(app, client, monkeypatch):
    monkeypatch.setitem(
        _container(app).capabilities.get("tts").providers, "fake-tts", FakeTTSProvider()
    )
    resp = client.post("/api/v1/tts", json={"text": "你好", "provider": "fake-tts"})
    assert resp.status_code == 200
    assert resp.mimetype == "audio/mpeg"
    assert resp.get_data().startswith(b"fake-mp3:")

    # 空文本校验
    resp = client.post("/api/v1/tts", json={"text": "", "provider": "fake-tts"})
    assert resp.status_code == 400


def test_tts_voices(app, client, monkeypatch):
    monkeypatch.setitem(
        _container(app).capabilities.get("tts").providers, "fake-tts", FakeTTSProvider()
    )
    resp = client.get("/api/v1/tts/voices?provider=fake-tts")
    data = resp.get_json()["data"]
    assert data["provider"] == "fake-tts"
    assert data["voices"] == [{"id": "v1", "label": "音色一"}]


def test_digital_human_config_and_image(client):
    # 默认配置
    data = client.get("/api/v1/digital_human").get_json()["data"]
    assert data["speaking"] is False
    assert data["image_url"] == ""

    # 更新动画参数
    resp = client.post(
        "/api/v1/digital_human",
        json={"breath_speed": 2.0, "swing_amplitude": 4.0, "blink": False},
    )
    data = resp.get_json()["data"]
    assert data["breath_speed"] == 2.0
    assert data["blink"] is False

    # 上传形象图
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    resp = client.post(
        "/api/v1/digital_human/image",
        data={"image": (io.BytesIO(png), "me.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["image_url"].startswith("/api/v1/digital_human/image?v=")

    # 获取形象图
    resp = client.get("/api/v1/digital_human/image")
    assert resp.status_code == 200
    assert resp.get_data() == png

    # 说话状态
    client.post("/api/v1/digital_human/state", json={"speaking": True})
    assert client.get("/api/v1/digital_human").get_json()["data"]["speaking"] is True


def test_digital_human_speak(app, client, monkeypatch):
    monkeypatch.setitem(
        _container(app).capabilities.get("tts").providers, "fake-tts", FakeTTSProvider()
    )
    resp = client.post("/api/v1/digital_human/speak", json={"text": "hi", "provider": "fake-tts"})
    assert resp.mimetype == "audio/mpeg"
    # speak 应标记 speaking 状态
    assert client.get("/api/v1/digital_human").get_json()["data"]["speaking"] is True


def test_chat_completions_non_stream(client, monkeypatch):
    container = _container(client.application)

    def fake_chat(session_id, message):
        return {"session_id": session_id or "s1", "reply": f"echo:{message}"}

    monkeypatch.setattr(container.runtime, "chat", fake_chat)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mcp-agent", "messages": [{"role": "user", "content": "你好"}]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "echo:你好"


def test_chat_completions_stream(client, monkeypatch):
    container = _container(client.application)

    async def fake_astream(session_id, message):
        for tok in ("你", "好"):
            yield {"type": "token", "content": tok}
        yield {"type": "done", "session_id": "s1", "reply": "你好"}

    monkeypatch.setattr(container.runtime, "astream", fake_astream)
    resp = client.post(
        "/v1/chat/completions",
        json={"stream": True, "messages": [{"role": "user", "content": "你好"}]},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    text = resp.get_data(as_text=True)
    assert '"delta"' in text
    assert "data: [DONE]" in text
    # 两个 token 分块都应出现在流中
    assert "你" in text and "好" in text


def test_chat_completions_token_auth(tmp_path, monkeypatch):
    config = AppConfig(data_dir=tmp_path, api_token="secret")
    config.ensure_dirs()
    app = create_app(config, start_background=False)
    client = app.test_client()

    # 无 Token → 401
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401

    # 正确 Token → 通过（演示模式回复）
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["choices"][0]["message"]["content"]
