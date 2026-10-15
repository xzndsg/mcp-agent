"""平台能力层：TTS / 视频 / 数字人等多模态能力的 provider 化封装。"""
from .base import Capability, CapabilityRegistry, Provider
from .digital_human.static_image import StaticImageHumanProvider
from .tts.edge import EdgeTTSProvider
from .video.stub import StubVideoProvider

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "Provider",
    "EdgeTTSProvider",
    "StubVideoProvider",
    "StaticImageHumanProvider",
]
