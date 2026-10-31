"""界面配色与字体。"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1c1c1c",
        "surface": "#232323",
        "surface_alt": "#262626",
        "border": "#303030",
        "border_strong": "#3a3a3a",
        "fg": "#fafafa",
        "muted": "#9a9a9a",
        "faint": "#6f6f6f",
        "accent": "#57c8ff",
        "accent_hover": "#7fd6ff",
        "on_accent": "#08202b",
        "hover": "#2e2e2e",
        "pressed": "#262626",
        "danger": "#c42b1c",
        "danger_pressed": "#a82417",
        "row_alt": "#202020",
        "titlebar": "#1c1c1c",
        "caption_fg": "#cfcfcf",
        "caption_hover_fg": "#ffffff",
    },
    "light": {
        "bg": "#fafafa",
        "surface": "#f1f1f1",
        "surface_alt": "#ececec",
        "border": "#e3e3e3",
        "border_strong": "#d0d0d0",
        "fg": "#1c1c1c",
        "muted": "#616161",
        "faint": "#8a8a8a",
        "accent": "#005fb8",
        "accent_hover": "#0078d4",
        "on_accent": "#ffffff",
        "hover": "#ececec",
        "pressed": "#e0e0e0",
        "danger": "#c42b1c",
        "danger_pressed": "#a82417",
        "row_alt": "#f4f4f4",
        "titlebar": "#fafafa",
        "caption_fg": "#3a3a3a",
        "caption_hover_fg": "#000000",
    },
}


def normalize_theme(value) -> str:
    return "light" if value == "light" else "dark"


def palette_for(theme: str) -> dict[str, str]:
    return PALETTES[normalize_theme(theme)]


def ui_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return ".AppleSystemUIFont"
    return "DejaVu Sans"


class Fonts:
    """集中创建 UI 字体；字号用磅值，随系统 DPI 自动缩放。"""

    def __init__(self, root: tk.Misc):
        family = ui_family()
        self.family = family
        self.body = tkfont.Font(root=root, name="AppBodyFont", family=family, size=10)
        self.body_strong = tkfont.Font(
            root=root, name="AppBodyStrongFont", family=family, size=10, weight="bold"
        )
        self.caption = tkfont.Font(root=root, name="AppCaptionFont", family=family, size=9)
        self.caption_strong = tkfont.Font(
            root=root, name="AppCaptionStrongFont", family=family, size=9, weight="bold"
        )
        self.title = tkfont.Font(
            root=root, name="AppTitleFont", family=family, size=11, weight="bold"
        )
        self.button = tkfont.Font(root=root, name="AppButtonFont", family=family, size=9)
        self.button_strong = tkfont.Font(
            root=root, name="AppButtonStrongFont", family=family, size=10, weight="bold"
        )

        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            try:
                tkfont.nametofont(name, root=root).configure(family=family, size=10)
            except tk.TclError:
                pass
