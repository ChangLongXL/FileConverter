"""转换核心：类型判定、唯一输出路径、图片与 FFmpeg 转换。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

VIDEO_FORMATS = ["mp4", "avi", "mov", "mkv", "webm"]
AUDIO_FORMATS = ["mp3", "wav", "aac", "flac", "ogg", "m4a"]
IMAGE_FORMATS = ["png", "jpg", "bmp", "webp", "tiff"]

_VIDEO_CODEC_FORMATS = {"mp4", "mov", "mkv", "avi", "webm"}
_AUDIO_CODEC_FORMATS = {"mp3", "wav", "aac", "flac", "ogg", "m4a"}
_VIDEO_AUDIO_CODEC = {
    "mp4": "aac",
    "mov": "aac",
    "mkv": "aac",
    "avi": "mp3",
    "webm": "libopus",
}

FFMPEG_CODEC = {
    "mp4": "libx264",
    "avi": "mpeg4",
    "mov": "libx264",
    "mkv": "libx264",
    "webm": "libvpx-vp9",
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "aac": "aac",
    "flac": "flac",
    "ogg": "libvorbis",
    "m4a": "aac",
}


def media_type_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def unique_output_path(
    src: Path,
    out_dir: Path,
    target_fmt: str,
    reserved: set[Path] | None = None,
) -> Path:
    """生成不与磁盘已有文件或同批次已分配路径冲突的输出路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{src.stem}.{target_fmt}"
    counter = 1
    while dst.exists() or (reserved is not None and dst in reserved):
        dst = out_dir / f"{src.stem}_{counter}.{target_fmt}"
        counter += 1
    if reserved is not None:
        reserved.add(dst)
    return dst


def convert_image(src: Path, dst: Path) -> None:
    """Pillow 转换；透明图转 JPEG 时用白色背景填充，避免黑底。"""
    with Image.open(src) as img:
        if dst.suffix.lower() in {".jpg", ".jpeg"}:
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
        else:
            if img.mode == "P":
                img = img.convert("RGBA")
        img.save(dst)


class ConversionCancelled(Exception):
    """用户停止转换时抛出。"""


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _tool_locations(name: str) -> list[Path]:
    """打包后优先使用程序目录里自带的 ffmpeg/ffprobe。"""
    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    roots: list[Path] = [Path(__file__).parent]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        roots.extend((exe_dir, exe_dir / "ffmpeg", exe_dir / "ffmpeg" / "bin"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base = Path(meipass)
            roots.extend((base, base / "ffmpeg", base / "ffmpeg" / "bin"))
    return [root / exe_name for root in roots]


def _find_tool(name: str) -> str | None:
    for candidate in _tool_locations(name):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _creation_flags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _probe_duration(src: Path) -> float | None:
    ffprobe = _find_tool("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                "-i", str(src),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in reversed(result.stdout.strip().splitlines()):
        try:
            return float(line.strip())
        except ValueError:
            continue
    return None


def build_ffmpeg_command(src: Path, dst: Path) -> list[str]:
    ffmpeg = _find_tool("ffmpeg") or "ffmpeg"
    fmt = dst.suffix.lstrip(".").lower()
    codec = FFMPEG_CODEC.get(fmt)
    args = [ffmpeg, "-y", "-i", str(src)]

    if fmt in _VIDEO_CODEC_FORMATS:
        args += ["-map", "0:v:0?", "-map", "0:a:0?"]
    elif fmt in _AUDIO_CODEC_FORMATS:
        args += ["-map", "0:a:0?"]

    if codec:
        if fmt in _VIDEO_CODEC_FORMATS:
            args += ["-c:v", codec]
            audio_codec = _VIDEO_AUDIO_CODEC.get(fmt)
            if audio_codec:
                args += ["-c:a", audio_codec]
        elif fmt in _AUDIO_CODEC_FORMATS:
            args += ["-c:a", codec]
        else:
            args += ["-c:v", codec]
    args.append(str(dst))
    return args


def convert_ffmpeg(
    src: Path,
    dst: Path,
    on_progress: Callable | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """调用 FFmpeg 转换，支持进度与取消。"""
    ffmpeg = _find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "未找到 ffmpeg。请安装 ffmpeg 并加入 PATH，或把 ffmpeg.exe 放到程序目录。"
        )
    if should_cancel is not None and should_cancel():
        raise ConversionCancelled()

    duration = _probe_duration(src)
    if should_cancel is not None and should_cancel():
        raise ConversionCancelled()
    command = build_ffmpeg_command(src, dst)
    command[0] = ffmpeg
    command[1:1] = ["-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 ffmpeg：{exc}") from exc

    tail: list[str] = []
    speed = 0.0
    code = 1

    def watch_cancel() -> None:
        while process.poll() is None:
            if should_cancel is not None and should_cancel():
                try:
                    process.terminate()
                except OSError:
                    pass
                return
            time.sleep(0.2)

    if should_cancel is not None:
        threading.Thread(target=watch_cancel, daemon=True).start()

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 20:
                del tail[0]

            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                except (ValueError, IndexError):
                    continue
                if on_progress is not None:
                    pct = None
                    if duration and duration > 0:
                        pct = max(0.0, min(99.9, seconds / duration * 100.0))
                    eta = None
                    if duration and duration > 0 and speed > 0:
                        eta = max(0.0, (duration - seconds) / speed)
                    on_progress(pct, speed or None, eta)
            elif line.startswith("speed="):
                try:
                    speed = float(line.split("=", 1)[1].rstrip("x"))
                except (ValueError, IndexError):
                    speed = 0.0
        code = process.wait()
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        if process.stdout is not None:
            process.stdout.close()

    if should_cancel is not None and should_cancel():
        _remove_quietly(dst)
        raise ConversionCancelled()
    if code != 0:
        _remove_quietly(dst)
        detail = "\n".join(tail[-6:]) or f"ffmpeg 退出码 {code}"
        raise RuntimeError(detail[:600])
    if on_progress is not None:
        on_progress(100.0, None, 0.0)