"""接口平台网关：能力发现 / TTS / 数字人 / OpenAI 兼容对话。

这是 mcp-agent 对外对接的关键层 —— Dify、Coze、自有前端等第三方系统
只需按 OpenAI 兼容协议调用本网关，即可复用整个 Agent 内核与工具生态。

- GET  /api/v1/capabilities              能力发现（多模态能力清单）
- GET  /api/v1/tts/voices                TTS 音色列表
- POST /api/v1/tts                       文本合成语音（audio/mpeg）
- GET  /api/v1/digital_human             数字人配置与状态
- POST /api/v1/digital_human             更新动画参数
- GET  /api/v1/digital_human/image       获取形象图
- POST /api/v1/digital_human/image       上传形象图（multipart）
- POST /api/v1/digital_human/speak       数字人开口说话（TTS + 状态标记）
- POST /api/v1/digital_human/state       更新说话状态
- POST /v1/chat/completions              OpenAI 兼容对话（stream / 非流式）
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

from ..core.logging_utils import get_logger
from .async_bridge import async_gen_to_sync
from .context import get_container
from .responses import fail, ok

logger = get_logger("gateway")

bp = Blueprint("gateway", __name__)

_MAX_TTS_CHARS = 1000


def _tts_provider(provider_name: str | None = None):
    cap = get_container().capabilities.get("tts")
    provider = cap.get(provider_name) if cap else None
    if provider is None or not provider.available():
        return None
    return provider


def _dh_provider():
    cap = get_container().capabilities.get("digital_human")
    return cap.get() if cap else None


def _check_token():
    """接口平台可选 Bearer 鉴权（未配置 MCP_AGENT_API_TOKEN 时不启用）。"""
    token = get_container().config.api_token
    if not token:
        return None
    if request.headers.get("Authorization", "") != f"Bearer {token}":
        return fail("鉴权失败：请携带 Authorization: Bearer <token>", http_status=401)
    return None


# ============================================================ 能力发现

@bp.get("/api/v1/capabilities")
def capabilities():
    return ok(get_container().capabilities.describe())


# ============================================================ TTS

@bp.get("/api/v1/tts/voices")
def tts_voices():
    provider = _tts_provider(request.args.get("provider"))
    if provider is None:
        return fail("TTS 能力不可用（未安装 edge-tts 或未接入 provider）")
    return ok({"provider": provider.name, "voices": provider.voices()})


@bp.post("/api/v1/tts")
def tts():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return fail("text 不能为空")
    provider = _tts_provider(data.get("provider"))
    if provider is None:
        return fail("TTS 能力不可用（未安装 edge-tts 或未接入 provider）")
    try:
        audio = provider.synthesize(text[:_MAX_TTS_CHARS], data.get("voice"), data.get("rate"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS 合成失败: %s", exc)
        return fail(f"语音合成失败: {exc}")
    return Response(audio, mimetype="audio/mpeg")


# ============================================================ 数字人

@bp.get("/api/v1/digital_human")
def dh_config():
    provider = _dh_provider()
    if provider is None:
        return fail("数字人能力不可用")
    return ok(provider.get_config())


@bp.post("/api/v1/digital_human")
def dh_update():
    provider = _dh_provider()
    if provider is None:
        return fail("数字人能力不可用")
    return ok(provider.set_config(request.get_json(silent=True) or {}))


@bp.get("/api/v1/digital_human/image")
def dh_image_get():
    provider = _dh_provider()
    if provider is None:
        return fail("数字人能力不可用")
    config = provider.get_config()
    if not config["image"]:
        return fail("尚未上传形象图", http_status=404)
    path = Path(provider.human_dir) / config["image"]
    if not path.exists():
        return fail("形象图文件不存在", http_status=404)
    return send_file(path)


@bp.post("/api/v1/digital_human/image")
def dh_image_upload():
    provider = _dh_provider()
    if provider is None:
        return fail("数字人能力不可用")
    file = request.files.get("image")
    if not file or not file.filename:
        return fail("请上传 image 文件")
    tmp = get_container().config.digital_human_dir / f"upload_{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    file.save(tmp)
    try:
        return ok(provider.set_image(str(tmp)))
    finally:
        tmp.unlink(missing_ok=True)


@bp.post("/api/v1/digital_human/speak")
def dh_speak():
    """数字人开口说话：TTS 合成音频，并标记 speaking 状态。"""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return fail("text 不能为空")
    tts_provider = _tts_provider(data.get("provider"))
    dh_provider = _dh_provider()
    if tts_provider is None or dh_provider is None:
        return fail("TTS / 数字人能力不可用")
    try:
        audio = tts_provider.synthesize(text[:_MAX_TTS_CHARS], data.get("voice"), data.get("rate"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("数字人语音合成失败: %s", exc)
        return fail(f"语音合成失败: {exc}")
    dh_provider.set_speaking(True)
    return Response(audio, mimetype="audio/mpeg")


@bp.post("/api/v1/digital_human/state")
def dh_state():
    provider = _dh_provider()
    if provider is None:
        return fail("数字人能力不可用")
    data = request.get_json(silent=True) or {}
    provider.set_speaking(bool(data.get("speaking", False)))
    return ok(provider.get_config())


# ============================================================ OpenAI 兼容对话

@bp.post("/v1/chat/completions")
def chat_completions():
    """OpenAI 兼容接口：Dify / Coze / OpenAI SDK 可直接对接。

    stream=false → 完整 JSON；stream=true → SSE chunk 流（data: {...} / [DONE]）。
    """
    denied = _check_token()
    if denied is not None:
        return denied

    container = get_container()
    data = request.get_json(force=True, silent=True) or {}
    messages = data.get("messages") or []
    stream = bool(data.get("stream", False))

    prompt = ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            prompt = str(msg.get("content") or "").strip()
            break
    if not prompt:
        return fail("messages 中需要至少一条 user 消息")

    session_id = str(data.get("user") or "") or None
    model = container.config.llm_model or "mcp-agent"
    created = int(time.time())

    if not stream:
        result = container.runtime.chat(session_id, prompt)
        return jsonify({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": result.get("reply", "")},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    # ---------- 流式 ----------
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    def _chunk(content: str | None = None, finish: str | None = None, role: str | None = None) -> str:
        delta: dict = {}
        if role:
            delta["role"] = role
        if content is not None:
            delta["content"] = content
        payload = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        yield _chunk(role="assistant", content="")
        agen = container.runtime.astream(session_id, prompt)
        for event in async_gen_to_sync(agen):
            if event["type"] == "token":
                yield _chunk(content=event["content"])
            elif event["type"] == "error":
                yield _chunk(content=f"\n[错误] {event['error']}")
        yield _chunk(finish="stop")
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
