"""微软 Edge TTS provider（edge-tts，免费、无需 API Key）。"""
from __future__ import annotations

import asyncio
from typing import Any

BUILTIN_VOICES: list[dict[str, str]] = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "晓晓（女·温柔）"},
    {"id": "zh-CN-YunxiNeural", "label": "云希（男·阳光）"},
    {"id": "zh-CN-YunyangNeural", "label": "云扬（男·新闻）"},
    {"id": "zh-CN-XiaoyiNeural", "label": "晓伊（女·活泼）"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北（女·东北）"},
    {"id": "en-US-JennyNeural", "label": "Jenny（英·女）"},
    {"id": "en-US-GuyNeural", "label": "Guy（英·男）"},
]


class EdgeTTSProvider:
    name = "edge-tts"

    def __init__(self, default_voice: str = "zh-CN-XiaoxiaoNeural") -> None:
        self.default_voice = default_voice

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    def metadata(self) -> dict[str, Any]:
        return {
            "title": "微软 Edge TTS",
            "vendor": "Microsoft",
            "free": True,
            "default_voice": self.default_voice,
        }

    def voices(self) -> list[dict[str, Any]]:
        return list(BUILTIN_VOICES)

    async def synthesize_async(
        self, text: str, voice: str | None = None, rate: str | None = None
    ) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(
            text, voice or self.default_voice, rate=rate or "+0%"
        )
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    def synthesize(
        self, text: str, voice: str | None = None, rate: str | None = None
    ) -> bytes:
        """异步 SDK 转同步（Flask 同步蓝图直接调用）。"""
        return asyncio.run(self.synthesize_async(text, voice, rate))
