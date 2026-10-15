"""WebSocket 接口 /ws。

消息协议（JSON 文本）：

客户端 → 服务端：
    {"type": "chat", "session_id": "可选", "message": "你好"}
    {"type": "ping"}

服务端 → 客户端：
    {"type": "token", "content": "..."}
    {"type": "tool_start" / "tool_end", ...}
    {"type": "done", "reply": "...", "session_id": "..."}
    {"type": "error", "error": "..."}
    {"type": "pong"}
"""
from __future__ import annotations

import json

from flask import Flask
from flask_sock import Sock

from .async_bridge import async_gen_to_sync
from .context import Container


def init_websocket(app: Flask, container: Container) -> None:
    sock = Sock(app)

    @sock.route("/ws")
    def ws_route(ws):  # noqa: ANN202 - flask-sock 的 Server 对象
        def send(payload: dict) -> None:
            ws.send(json.dumps(payload, ensure_ascii=False))

        while True:
            try:
                raw = ws.receive(timeout=300)
            except Exception:  # noqa: BLE001 - 超时 / 客户端断开均结束
                break
            if raw is None:
                break

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                send({"type": "error", "error": "消息必须是 JSON"})
                continue

            msg_type = message.get("type")
            if msg_type == "ping":
                send({"type": "pong"})
                continue

            if msg_type != "chat":
                send({"type": "error", "error": f"不支持的消息类型: {msg_type}"})
                continue

            text = (message.get("message") or "").strip()
            if not text:
                send({"type": "error", "error": "message 不能为空"})
                continue

            session_id = message.get("session_id")
            try:
                agen = container.runtime.astream(session_id, text)
                for event in async_gen_to_sync(agen):
                    send(event)
            except Exception as exc:  # noqa: BLE001
                send({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
