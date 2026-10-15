"""对话与系统接口：

- GET  /api/health           健康检查
- GET  /api/runtime          运行时信息（LLM 厂商/模型/工具数/会话数）
- POST /api/chat             同步对话
- GET  /api/chat/stream      SSE 流式对话（EventSource 仅支持 GET）
- DELETE /api/sessions/<id>  清空会话
"""
from __future__ import annotations

import json

from flask import Blueprint, Response, request

from .. import __version__
from ..core.config import LLM_PROVIDERS
from .async_bridge import async_gen_to_sync
from .context import get_container
from .responses import fail, ok

bp = Blueprint("rest", __name__)


@bp.get("/api/health")
def health():
    container = get_container()
    return ok(
        {
            "status": "up",
            "version": __version__,
            "llm_ready": container.runtime.llm_ready,
        }
    )


@bp.get("/api/runtime")
def runtime_info():
    container = get_container()
    cfg = container.config
    return ok(
        {
            "version": __version__,
            "llm": {
                "provider": cfg.llm_provider,
                "model": cfg.llm_model,
                "base_url": cfg.llm_base_url,
                "ready": cfg.llm_ready,
                "available_providers": list(LLM_PROVIDERS.keys()),
            },
            "tool_count": len(container.registry.get_enabled_tools()),
            "servers": container.manager.list_servers(),
            "sessions": container.runtime.sessions.stats(),
        }
    )


@bp.post("/api/chat")
def chat():
    container = get_container()
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return fail("message 不能为空")
    session_id = data.get("session_id") or None
    result = container.runtime.chat(session_id, message)
    return ok(result)


@bp.get("/api/chat/stream")
def chat_stream():
    """SSE：事件为 token / tool_start / tool_end / done / error。"""
    container = get_container()
    message = (request.args.get("message") or "").strip()
    if not message:
        return fail("message 不能为空")
    session_id = request.args.get("session_id") or None

    def generate():
        agen = container.runtime.astream(session_id, message)
        for event in async_gen_to_sync(agen):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.delete("/api/sessions/<session_id>")
def clear_session(session_id: str):
    container = get_container()
    removed = container.runtime.sessions.clear(session_id)
    return ok({"removed": removed})
