"""TTS（文本转语音）能力协议。"""
from __future__ import annotations

from typing import Any, Protocol


class TTSProvider(Protocol):
    """TTS provider 协议：在 Provider 最小协议之上追加合成接口。"""

    name: str

    def available(self) -> bool: ...
    def metadata(self) -> dict[str, Any]: ...

    def voices(self) -> list[dict[str, Any]]:
        """可用音色列表：[{id, label}]。"""
        ...

    def synthesize(self, text: str, voice: str | None = None, rate: str | None = None) -> bytes:
        """同步合成，返回音频字节（mp3）。"""
        ...
