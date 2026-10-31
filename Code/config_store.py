"""配置持久化：读取 / 保存 config.json，带类型与异常兜底。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "theme": "dark",
    "window_geometry": "",
    "window_maximized": False,
    "output_dir": "./output/",
    "image_format": "png",
    "video_format": "mp4",
    "audio_format": "mp3",
}


class ConfigStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data: dict = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(loaded, dict):
            return
        for key, default_value in DEFAULT_CONFIG.items():
            if key not in loaded:
                continue
            value = loaded[key]
            if isinstance(value, type(default_value)):
                self.data[key] = value

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value