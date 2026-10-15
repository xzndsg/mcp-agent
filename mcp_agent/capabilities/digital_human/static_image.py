"""静态图数字人 provider（零 GPU 轻量版）。

原理：后端只负责保存形象图与动画参数；前端用 CSS 动画（呼吸 / 眨眼 /
摆动）叠加 WebAudio 音频振幅驱动"说话"状态。后续可平滑替换为
SadTalker / EchoMimic 等真渲染 provider，协议不变。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "image": "",  # 相对 data_dir/digital_human 的形象图文件名
    "breath_speed": 3.0,  # 呼吸周期（秒，越小越快）
    "swing_amplitude": 2.0,  # 说话摆动最大角度（deg）
    "blink": True,  # 是否启用眨眼动画
}

ALLOWED_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")


class StaticImageHumanProvider:
    name = "static-image"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.human_dir = self.data_dir / "digital_human"
        self.config_file = self.human_dir / "config.json"
        self.speaking = False
        self._config: dict[str, Any] | None = None

    # ---------------------------------------------------------- 持久化
    def _load(self) -> dict[str, Any]:
        if self._config is None:
            config = dict(DEFAULT_CONFIG)
            if self.config_file.exists():
                try:
                    config.update(json.loads(self.config_file.read_text("utf-8")))
                except (json.JSONDecodeError, OSError):
                    pass
            self._config = config
        return self._config

    def _save(self) -> None:
        self.human_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2), "utf-8"
        )

    # ---------------------------------------------------------- 协议实现
    def available(self) -> bool:
        return True

    def metadata(self) -> dict[str, Any]:
        return {
            "title": "静态图数字人（CSS 动画 + 音频振幅驱动）",
            "vendor": "mcp-agent 内置",
            "image_ready": bool(self._load()["image"]),
            "upgrade_hint": "可替换为 SadTalker / EchoMimic 等真渲染 provider",
        }

    def get_config(self) -> dict[str, Any]:
        config = dict(self._load())
        image_path = self.human_dir / str(config["image"])
        exists = bool(config["image"]) and image_path.exists()
        config["image_url"] = (
            f"/api/v1/digital_human/image?v={int(image_path.stat().st_mtime)}"
            if exists
            else ""
        )
        config["speaking"] = self.speaking
        return config

    def set_config(self, data: dict[str, Any]) -> dict[str, Any]:
        config = self._load()
        for key in ("breath_speed", "swing_amplitude", "blink"):
            if data.get(key) is not None:
                config[key] = data[key]
        self._save()
        return self.get_config()

    def set_image(self, file_path: str) -> dict[str, Any]:
        suffix = Path(file_path).suffix.lower() or ".png"
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"不支持的图片格式: {suffix}（支持 {', '.join(ALLOWED_SUFFIXES)}）")
        self.human_dir.mkdir(parents=True, exist_ok=True)
        target = self.human_dir / f"avatar{suffix}"
        shutil.copyfile(file_path, target)
        self._load()["image"] = target.name
        for old in self.human_dir.glob("avatar.*"):  # 清理旧格式
            if old.name != target.name:
                old.unlink()
        self._save()
        return self.get_config()

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = speaking
