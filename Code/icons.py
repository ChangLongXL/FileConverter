"""SVG 图标渲染与导出。"""
from __future__ import annotations

import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

# PyInstaller 等打包工具会把数据解压到 _MEIPASS。
ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
SUPERSAMPLE = 6

_TOKEN_RE = re.compile(
    r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
)

_render_cache: dict[tuple, Image.Image] = {}
_photo_cache: dict[tuple, ImageTk.PhotoImage] = {}


# ---------------------------------------------------------------- SVG path
def _flatten_quad(p0, p1, p2, steps=20):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        pts.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return pts


def _flatten_cubic(p0, p1, p2, p3, steps=24):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        pts.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return pts


def _path_subpaths(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """把 path 的 d 属性拆成若干子路径（点列 + 是否闭合）。"""
    tokens = _TOKEN_RE.findall(d or "")
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    pts: list[tuple[float, float]] = []
    cur = start = (0.0, 0.0)
    closed = False
    cmd = "M"
    i = 0

    def flush() -> None:
        nonlocal pts, closed
        if len(pts) >= 2:
            subpaths.append((pts[:], closed))
        pts = []
        closed = False

    def read() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                closed = True
                flush()
                cur = start
                continue
        upper = cmd.upper()
        rel = cmd.islower()

        if upper == "M":
            x, y = read(), read()
            if rel:
                x += cur[0]
                y += cur[1]
            flush()
            cur = start = (x, y)
            pts = [(x, y)]
            cmd = "L" if not rel else "l"
        elif upper == "L":
            x, y = read(), read()
            if rel:
                x += cur[0]
                y += cur[1]
            cur = (x, y)
            pts.append(cur)
        elif upper == "H":
            x = read()
            if rel:
                x += cur[0]
            cur = (x, cur[1])
            pts.append(cur)
        elif upper == "V":
            y = read()
            if rel:
                y += cur[1]
            cur = (cur[0], y)
            pts.append(cur)
        elif upper == "C":
            x1, y1, x2, y2, x, y = (read() for _ in range(6))
            if rel:
                x1 += cur[0]; y1 += cur[1]
                x2 += cur[0]; y2 += cur[1]
                x += cur[0]; y += cur[1]
            pts.extend(_flatten_cubic(cur, (x1, y1), (x2, y2), (x, y)))
            cur = (x, y)
        elif upper == "Q":
            x1, y1, x, y = (read() for _ in range(4))
            if rel:
                x1 += cur[0]; y1 += cur[1]
                x += cur[0]; y += cur[1]
            pts.extend(_flatten_quad(cur, (x1, y1), (x, y)))
            cur = (x, y)
        else:
            break
    flush()
    return subpaths


# ---------------------------------------------------------------- painting
def _color(value: str | None, color: str, on_accent: str):
    if not value:
        return None
    value = value.strip()
    if value in ("none", "transparent"):
        return None
    if value == "currentColor":
        return color
    if value.startswith("var("):
        return on_accent
    return value


def _stroke(draw: ImageDraw.ImageDraw, pts, color, width: float, closed: bool, cap: str) -> None:
    if len(pts) < 2:
        return
    line = list(pts)
    if closed and line[0] != line[-1]:
        line.append(line[0])
    w = max(1, int(round(width)))
    draw.line(line, fill=color, width=w, joint="curve")
    if cap == "round" and not closed:
        r = w / 2.0
        for x, y in (line[0], line[-1]):
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _render(name: str, size: int, color: str, on_accent: str) -> Image.Image:
    key = (name, size, color, on_accent)
    cached = _render_cache.get(key)
    if cached is not None:
        return cached

    svg_text = (ASSET_DIR / f"{name}.svg").read_text(encoding="utf-8")
    root = ET.fromstring(svg_text)
    view = [float(v) for v in (root.get("viewBox") or "0 0 24 24").replace(",", " ").split()]
    vx, vy, vw, vh = view

    canvas_px = size * SUPERSAMPLE
    scale = canvas_px / max(vw, vh)
    image = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def map_pt(x: float, y: float) -> tuple[float, float]:
        return ((x - vx) * scale, (y - vy) * scale)

    for el in root:
        tag = el.tag.rsplit("}", 1)[-1]
        fill = _color(el.get("fill"), color, on_accent)
        stroke = _color(el.get("stroke"), color, on_accent)
        stroke_w = float(el.get("stroke-width", "1")) * scale
        cap = el.get("stroke-linecap", "butt")

        if tag == "path":
            for pts, closed in _path_subpaths(el.get("d", "")):
                mapped = [map_pt(x, y) for x, y in pts]
                if fill and len(mapped) >= 3:
                    draw.polygon(mapped, fill=fill)
                if stroke:
                    _stroke(draw, mapped, stroke, stroke_w, closed, cap)
        elif tag == "rect":
            x = float(el.get("x", 0)); y = float(el.get("y", 0))
            w = float(el.get("width", 0)); h = float(el.get("height", 0))
            rx = float(el.get("rx", el.get("ry", 0)))
            x0, y0 = map_pt(x, y)
            x1, y1 = map_pt(x + w, y + h)
            radius = min(rx * scale, (x1 - x0) / 2, (y1 - y0) / 2)
            if radius > 0:
                draw.rounded_rectangle(
                    (x0, y0, x1, y1), radius=radius, fill=fill,
                    outline=stroke, width=max(1, int(round(stroke_w))) if stroke else 0,
                )
            else:
                draw.rectangle(
                    (x0, y0, x1, y1), fill=fill,
                    outline=stroke, width=max(1, int(round(stroke_w))) if stroke else 0,
                )
        elif tag == "circle":
            cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0))
            r = float(el.get("r", 0))
            px, py = map_pt(cx, cy)
            pr = r * scale
            draw.ellipse(
                (px - pr, py - pr, px + pr, py + pr), fill=fill,
                outline=stroke, width=max(1, int(round(stroke_w))) if stroke else 0,
            )
        elif tag == "line":
            x1, y1 = map_pt(float(el.get("x1", 0)), float(el.get("y1", 0)))
            x2, y2 = map_pt(float(el.get("x2", 0)), float(el.get("y2", 0)))
            if stroke:
                _stroke(draw, [(x1, y1), (x2, y2)], stroke, stroke_w, False, cap)
        elif tag in ("polygon", "polyline"):
            raw = [float(v) for v in (el.get("points") or "").replace(",", " ").split()]
            pts = [map_pt(raw[k], raw[k + 1]) for k in range(0, len(raw) - 1, 2)]
            if fill and tag == "polygon" and len(pts) >= 3:
                draw.polygon(pts, fill=fill)
            if stroke:
                _stroke(draw, pts, stroke, stroke_w, tag == "polygon", cap)

    image = image.resize((size, size), Image.LANCZOS)
    _render_cache[key] = image
    return image


def icon_image(name: str, size: int, color: str, on_accent: str = "#000000") -> Image.Image:
    """渲染指定图标，返回 RGBA 图像。"""
    return _render(name, size, color, on_accent)


def icon_photo(master, name: str, size: int, color: str, on_accent: str = "#000000") -> ImageTk.PhotoImage:
    """渲染并缓存 PhotoImage（同一尺寸/配色只渲染一次）。"""
    key = (name, size, color, on_accent)
    photo = _photo_cache.get(key)
    if photo is None:
        photo = ImageTk.PhotoImage(_render(name, size, color, on_accent), master=master)
        _photo_cache[key] = photo
    return photo


def write_app_icon(path: Path | str, color: str, on_accent: str) -> Path:
    """把 SVG 应用图标导出为多尺寸 .ico，供 Windows 任务栏使用。"""
    target = Path(path)
    image = _render("app", 256, color, on_accent)
    image.save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return target


def temp_icon_path(theme: str) -> Path:
    return Path(tempfile.gettempdir()) / f"file_converter_icon_{theme}.ico"
