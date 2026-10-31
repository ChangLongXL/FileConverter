"""无边框窗口：任务栏注册、拖动、缩放与窗口状态。"""
from __future__ import annotations

import ctypes
import re
import sys
import tkinter as tk
from typing import Callable

from icons import icon_photo, temp_icon_path, write_app_icon

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi

    _user32.SendMessageW.restype = ctypes.c_void_p
    _user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    _user32.SetWindowPos.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    _user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _user32.GetParent.argtypes = [ctypes.c_void_p]
    _user32.GetParent.restype = ctypes.c_void_p
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.LoadImageW.restype = ctypes.c_void_p
    _user32.LoadImageW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    _user32.SetClassLongPtrW.restype = ctypes.c_void_p
    _user32.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    _user32.GetClassLongPtrW.restype = ctypes.c_void_p
    _user32.GetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint
    ]

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", ctypes.c_ulong),
        ]

    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
    _user32.GetMonitorInfoW.restype = ctypes.c_int

GWL_EXSTYLE = -20
GWL_STYLE = -16
GCL_STYLE = -26
GCLP_HICON = -14
GCLP_HICONSM = -34
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
CS_DROPSHADOW = 0x00020000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SW_MINIMIZE = 6
SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


class WindowChrome:
    def __init__(
        self,
        root: tk.Tk,
        scale: float,
        palette: dict[str, str],
        theme: str,
        min_size: tuple[int, int],
        on_close: Callable[[], None],
    ):
        self.root = root
        self.scale = scale
        self.palette = palette
        self.theme = theme
        self.on_close = on_close
        self.min_size = (int(min_size[0] * scale), int(min_size[1] * scale))
        self.maximized = False
        self.titlebar_height = int(46 * scale)
        self.on_maximize_change: Callable[[bool], None] | None = None

        self._hwnd: int | None = None
        self._hicons: list[int] = []
        self._big_icon: int = 0
        self._small_icon: int = 0
        self._normal_geometry: str | None = None
        self._max_rect: tuple[int, int, int, int] | None = None
        self._drag: dict | None = None
        self._drag_armed = False
        self._resize: dict | None = None
        self._resizers: dict[str, tk.Frame] = {}
        self._edge_size = max(3, int(5 * scale))
        self._corner_size = max(8, int(12 * scale))
        self.caption_width = int(38 * 3 * scale)
        self._curtain: tk.Frame | None = None
        self._curtain_icon: tk.Label | None = None

        root.minsize(*self.min_size)

    # ------------------------------------------------------------ 安装
    def prepare(self) -> None:
        self.root.configure(bg=self.palette["bg"])
        self.root.overrideredirect(True)
        if IS_WINDOWS:
            self.root.update_idletasks()
            self._hwnd = self._resolve_hwnd()
            self._apply_taskbar_style()
            self._enable_dwm()

    def _resolve_hwnd(self) -> int:
        wid = self.root.winfo_id()
        parent = _user32.GetParent(wid)
        return int(parent or wid)

    def _apply_taskbar_style(self) -> None:
        if not IS_WINDOWS or not self._hwnd:
            return
        style = _user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        _user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
        _user32.SetWindowPos(
            self._hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )

    def _enable_dwm(self) -> None:
        if not IS_WINDOWS or not self._hwnd:
            return
        self._round_corners(True)
        try:
            class_style = int(_user32.GetClassLongPtrW(self._hwnd, GCL_STYLE) or 0)
            _user32.SetClassLongPtrW(self._hwnd, GCL_STYLE, class_style | CS_DROPSHADOW)
        except Exception:
            pass

    def _round_corners(self, rounded: bool) -> None:
        if not IS_WINDOWS or not self._hwnd:
            return
        try:
            preference = ctypes.c_int(DWMWCP_ROUND if rounded else DWMWCP_DONOTROUND)
            _dwmapi.DwmSetWindowAttribute(
                self._hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference), ctypes.sizeof(preference),
            )
        except Exception:
            pass

    def _set_window_icon(self) -> None:
        if not IS_WINDOWS or not self._hwnd:
            return
        try:
            if not self._big_icon:
                ico = temp_icon_path(self.theme)
                write_app_icon(ico, self.palette["accent"], self.palette["on_accent"])
                self._big_icon = int(
                    _user32.LoadImageW(None, str(ico), IMAGE_ICON, 64, 64, LR_LOADFROMFILE) or 0
                )
                self._small_icon = int(
                    _user32.LoadImageW(None, str(ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE) or 0
                )
            if self._big_icon:
                _user32.SendMessageW(self._hwnd, 0x0080, 1, self._big_icon)
                _user32.SetClassLongPtrW(self._hwnd, GCLP_HICON, self._big_icon)
                if self._big_icon not in self._hicons:
                    self._hicons.append(self._big_icon)
            if self._small_icon:
                _user32.SendMessageW(self._hwnd, 0x0080, 0, self._small_icon)
                _user32.SetClassLongPtrW(self._hwnd, GCLP_HICONSM, self._small_icon)
                if self._small_icon not in self._hicons:
                    self._hicons.append(self._small_icon)
        except Exception:
            pass

    def refresh(self) -> None:
        """窗口显示后重新同步任务栏样式与图标。"""
        if not IS_WINDOWS:
            return
        self._hwnd = self._resolve_hwnd()
        self._apply_taskbar_style()
        self._set_window_icon()

    def install_resizers(self) -> None:
        """安装边缘/角落缩放热区。"""
        self._resizers = {}
        for cursor, edge in (
            ("size_ns", "n"),
            ("size_ns", "s"),
            ("size_we", "w"),
            ("size_we", "e"),
            ("size_nw_se", "nw"),
            ("size_ne_sw", "sw"),
            ("size_nw_se", "se"),
        ):
            self._resizers[edge] = self._make_resizer(cursor, edge)

        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self._layout_resizers(self.root.winfo_width(), self.root.winfo_height())

    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self._layout_resizers(event.width, event.height)

    def _layout_resizers(self, width: int, height: int) -> None:
        edge = self._edge_size
        corner = self._corner_size
        top_width = max(0, width - self.caption_width)
        side_height = max(0, height - self.titlebar_height)

        top = self._resizers.get("n")
        if top is not None:
            if top_width > 0:
                top.place(x=0, y=0, width=top_width, height=edge)
            else:
                top.place_forget()
        bottom = self._resizers.get("s")
        if bottom is not None:
            bottom.place(x=0, y=max(0, height - edge), width=width, height=edge)
        left = self._resizers.get("w")
        if left is not None:
            left.place(x=0, y=0, width=edge, height=height)
        right = self._resizers.get("e")
        if right is not None:
            right.place(
                x=max(0, width - edge),
                y=self.titlebar_height,
                width=edge,
                height=side_height,
            )

        nw = self._resizers.get("nw")
        if nw is not None:
            nw.place(x=0, y=0, width=corner, height=corner)
        sw = self._resizers.get("sw")
        if sw is not None:
            sw.place(x=0, y=max(0, height - corner), width=corner, height=corner)
        se = self._resizers.get("se")
        if se is not None:
            se.place(
                x=max(0, width - corner),
                y=max(0, height - corner),
                width=corner,
                height=corner,
            )

    def _make_resizer(self, cursor: str, edge: str) -> tk.Frame:
        frame = tk.Frame(self.root, bg=self.palette["bg"], bd=0, highlightthickness=0)
        frame.configure(cursor=cursor)
        frame.bind("<ButtonPress-1>", lambda event, e=edge: self._start_resize(e, event))
        frame.bind("<B1-Motion>", self._on_resize)
        frame.bind("<ButtonRelease-1>", self._end_resize)
        return frame

    # ------------------------------------------------------------ 拖动
    def attach_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_motion, add="+")
        widget.bind("<ButtonRelease-1>", self._drag_end, add="+")
        widget.bind("<Double-Button-1>", self._title_double_click, add="+")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_armed = self.maximized
        if self.maximized:
            self._drag = {
                "x": event.x_root, "y": event.y_root,
                "ratio": 0.5, "started": False,
            }
            rect = self._max_rect
            if rect and rect[2] > 0:
                self._drag["ratio"] = min(1.0, max(0.0, (event.x_root - rect[0]) / rect[2]))
            return
        self._drag = {
            "x": event.x_root, "y": event.y_root,
            "ox": event.x_root - self.root.winfo_x(),
            "oy": event.y_root - self.root.winfo_y(),
            "started": False,
        }

    def _drag_motion(self, event: tk.Event) -> None:
        if not self._drag:
            return
        if self.maximized:
            if not self._drag_armed:
                return
            if abs(event.x_root - self._drag["x"]) + abs(event.y_root - self._drag["y"]) < int(4 * self.scale):
                return
            ratio = self._drag["ratio"]
            self.restore()
            width = self.root.winfo_width()
            x = int(event.x_root - width * ratio)
            y = int(event.y_root - self.titlebar_height // 2)
            self._drag = {
                "x": event.x_root, "y": event.y_root,
                "ox": event.x_root - x, "oy": event.y_root - y,
                "started": True,
            }
            self._drag_armed = False
            self.root.geometry(f"+{x}+{y}")
            return
        x = event.x_root - self._drag["ox"]
        y = event.y_root - self._drag["oy"]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, event: tk.Event) -> None:
        self._drag = None
        self._drag_armed = False

    def _title_double_click(self, event: tk.Event) -> str:
        self.toggle_maximize()
        return "break"

    # ------------------------------------------------------------ 缩放
    _RESIZE_CURSORS = {
        "n": "size_ns", "s": "size_ns",
        "e": "size_we", "w": "size_we",
        "nw": "size_nw_se", "se": "size_nw_se",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
    }

    def _start_resize(self, edge: str, event: tk.Event) -> None:
        if self.maximized:
            return
        self._resize = {
            "edge": edge,
            "px": event.x_root,
            "py": event.y_root,
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
            "w": self.root.winfo_width(),
            "h": self.root.winfo_height(),
            "curtain": False,
        }

    def _on_resize(self, event: tk.Event) -> None:
        if not self._resize:
            return
        state = self._resize
        if not state["curtain"]:
            state["curtain"] = True
            self._show_curtain(self._RESIZE_CURSORS.get(state["edge"], "size_nw_se"))

        dx = event.x_root - state["px"]
        dy = event.y_root - state["py"]
        edge = state["edge"]
        x, y, w, h = state["x"], state["y"], state["w"], state["h"]
        min_w, min_h = self.min_size

        if "w" in edge:
            new_x = x + dx
            new_w = w - dx
            if new_w < min_w:
                new_x = x + w - min_w
                new_w = min_w
            x, w = new_x, new_w
        if "e" in edge:
            w = max(min_w, w + dx)
        if "n" in edge:
            new_y = y + dy
            new_h = h - dy
            if new_h < min_h:
                new_y = y + h - min_h
                new_h = min_h
            y, h = new_y, new_h
        if "s" in edge:
            h = max(min_h, h + dy)

        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _end_resize(self, event: tk.Event) -> None:
        self._resize = None
        self._hide_curtain()

    def _show_curtain(self, cursor: str) -> None:
        """缩放时用幕布遮住窗口。"""
        if self._curtain is None:
            curtain = tk.Frame(
                self.root, bg=self.palette["bg"], bd=0, highlightthickness=0
            )
            icon_size = int(72 * self.scale)
            icon = tk.Label(
                curtain,
                image=icon_photo(
                    self.root, "app", icon_size,
                    self.palette["accent"], self.palette["on_accent"],
                ),
                bg=self.palette["bg"],
                bd=0,
                highlightthickness=0,
            )
            icon.place(relx=0.5, rely=0.5, anchor="center")
            self._curtain = curtain
            self._curtain_icon = icon
        self._curtain.configure(cursor=cursor)
        self._curtain_icon.configure(cursor=cursor)
        self._curtain.place(x=0, y=0, relwidth=1, relheight=1)
        self._curtain.lift()

    def _hide_curtain(self) -> None:
        if self._curtain is not None:
            self._curtain.place_forget()

    # ------------------------------------------------------------ 窗口状态
    def minimize(self) -> None:
        if IS_WINDOWS and self._hwnd:
            _user32.ShowWindow(self._hwnd, SW_MINIMIZE)
        else:
            self.root.iconify()

    def toggle_maximize(self) -> None:
        if self.maximized:
            self.restore()
        else:
            self.maximize()

    def maximize(self) -> None:
        if self.maximized:
            return
        self._normal_geometry = self._current_geometry()
        rect = self._work_area()
        self._max_rect = rect
        self.maximized = True
        self._round_corners(False)
        self.root.geometry(f"{rect[2]}x{rect[3]}+{rect[0]}+{rect[1]}")
        self._notify_maximize()

    def restore(self) -> None:
        if not self.maximized:
            return
        self.maximized = False
        if self._normal_geometry:
            self.root.geometry(self._normal_geometry)
        self._max_rect = None
        self._round_corners(True)
        self._notify_maximize()

    def _notify_maximize(self) -> None:
        if self.on_maximize_change is not None:
            self.on_maximize_change(self.maximized)

    def close(self) -> None:
        self.on_close()

    def _current_geometry(self) -> str:
        return self.root.geometry()

    def _work_area(self) -> tuple[int, int, int, int]:
        if IS_WINDOWS and self._hwnd:
            try:
                monitor = _user32.MonitorFromWindow(self._hwnd, MONITOR_DEFAULTTONEAREST)
                info = _MONITORINFO()
                info.cbSize = ctypes.sizeof(_MONITORINFO)
                if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    rect = info.rcWork
                    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            except Exception:
                pass
        return (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())

    # ------------------------------------------------------------ 几何保存/恢复
    def restore_geometry(self, geometry: str | None, maximized: bool) -> tuple[int, int]:
        work = self._work_area()
        width, height = self._default_size()
        x = work[0] + (work[2] - width) // 2
        y = work[1] + (work[3] - height) // 2

        match = _GEOMETRY_RE.match(geometry or "")
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            x, y = int(match.group(3)), int(match.group(4))

        width = min(max(width, self.min_size[0]), work[2])
        height = min(max(height, self.min_size[1]), work[3])
        x = min(max(x, work[0]), work[0] + work[2] - width)
        y = min(max(y, work[1]), work[1] + work[3] - height)

        normal = f"{width}x{height}+{x}+{y}"
        self._normal_geometry = normal
        self.root.geometry(normal)

        if maximized:
            self.maximized = True
            self._max_rect = work
            self._round_corners(False)
            self.root.geometry(f"{work[2]}x{work[3]}+{work[0]}+{work[1]}")
            self._notify_maximize()
        return width, height

    def _default_size(self) -> tuple[int, int]:
        return (int(800 * self.scale), int(640 * self.scale))

    def save_geometry(self) -> str:
        if self.maximized and self._normal_geometry:
            return self._normal_geometry
        try:
            return self.root.geometry()
        except tk.TclError:
            return self._normal_geometry or ""

    def is_maximized(self) -> bool:
        return self.maximized
