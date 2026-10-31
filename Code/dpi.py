"""高 DPI 支持。优先使用 tkinter-unblur，否则在 Windows 上通过 ctypes 设置。"""
from __future__ import annotations
import sys

def create_root():
    try:
        from tkinter_unblur import Tk
        return Tk(), True
    except Exception:
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
        import tkinter as tk
        return tk.Tk(), False