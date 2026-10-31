"""自绘小组件。"""
from __future__ import annotations

import tkinter as tk


class ProgressBar(tk.Canvas):
    """细长的圆角进度条（ttk 主题的进度条在高 DPI 下过细）。"""

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int,
        height: int,
        background: str,
        trough: str,
        fill: str,
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            bg=background,
            bd=0,
            highlightthickness=0,
            takefocus=0,
        )
        self._width = width
        self._height = height
        self._value = 0.0
        y = height / 2
        radius = height / 2
        self._trough = self.create_line(
            radius, y, width - radius, y,
            width=height, capstyle="round", fill=trough,
        )
        self._fill_item = self.create_line(
            radius, y, radius, y,
            width=height, capstyle="round", fill=fill, state="hidden",
        )
        self.set(0)

    def set(self, value: float) -> None:
        value = max(0.0, min(100.0, float(value)))
        self._value = value
        y = self._height / 2
        radius = self._height / 2
        start = radius
        end = radius + (self._width - 2 * radius) * value / 100.0
        if value <= 0:
            self.itemconfigure(self._fill_item, state="hidden")
            return
        self.coords(self._fill_item, start, y, max(start, end), y)
        self.itemconfigure(self._fill_item, state="normal")
