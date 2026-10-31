"""File Converter 主界面与转换调度。"""
from __future__ import annotations
import os
import queue
import sys
import threading
import tkinter as tk
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import sv_ttk

from chrome import WindowChrome
from config_store import ConfigStore
from core import (
    AUDIO_FORMATS, IMAGE_FORMATS, VIDEO_FORMATS, ConversionCancelled,
    convert_ffmpeg, convert_image, media_type_of, unique_output_path,
)
from icons import icon_photo
from theme import Fonts, normalize_theme, palette_for
from titlebar import TitleBar
from widgets import ProgressBar

APP_TITLE = "File Converter"
APP_VERSION = "1.0"
BUILD_DATE = "2026.10.31"
AUTHOR = "ChangLongXL"
PROJECT_URL = "https://github.com/ChangLongXL/FileConverter"
DEFAULT_OUTPUT_DIR = "./output/"
BASE_WINDOW_SIZE = (800, 640)
BASE_MIN_SIZE = (680, 540)


def _default_config_path() -> Path:
    """源码运行时配置放在项目目录，打包后写到用户可写目录。"""
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        return base / "FileConverter" / "config.json"
    return Path(__file__).with_name("config.json")


CONFIG_PATH = _default_config_path()
_TYPE_LABEL = {"video": "视频", "audio": "音频", "image": "图片"}


def _app_dir() -> Path:
    """相对输出路径以程序所在目录为基准，避免受启动时工作目录影响。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _resolve_output(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else _app_dir() / path


class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)

        self.scale = root.winfo_fpixels('1i') / 96.0
        if self.scale < 1.0:
            self.scale = 1.0
        self.root.tk.call('tk', 'scaling', root.winfo_fpixels('1i') / 72.0)

        self.config = ConfigStore(CONFIG_PATH)
        self.theme_name = normalize_theme(self.config.get("theme", "dark"))
        sv_ttk.set_theme(self.theme_name)

        self.palette = palette_for(self.theme_name)
        self.fonts = Fonts(self.root)
        self._configure_style()

        self.files: list[Path] = []
        self._file_keys: set[str] = set()
        self._item_path: dict[str, Path] = {}
        self.ui_queue: queue.Queue = queue.Queue()
        self.converting = False
        self.stop_requested = False
        self._worker: threading.Thread | None = None

        self.chrome = WindowChrome(
            self.root,
            scale=self.scale,
            palette=self.palette,
            theme=self.theme_name,
            min_size=BASE_MIN_SIZE,
            on_close=self._on_close,
        )
        self.chrome.prepare()

        self._build_ui()
        self._restore_config()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Alt-F4>", lambda _event: self._on_close())
        self._poll_ui_queue()
        self.root.after(400, self.chrome.refresh)

    def pad(self, value: float) -> int:
        return int(value * self.scale)

    # ---------------------------------------------------------------- 样式
    def _configure_style(self) -> None:
        style = ttk.Style()
        self.root.option_add("*TCombobox*Listbox.font", self.fonts.body)

        style.configure(".", font=self.fonts.body)
        style.configure("TButton", font=self.fonts.button, padding=(self.pad(14), self.pad(6)))
        style.configure(
            "Toolbar.TButton", font=self.fonts.button, padding=(self.pad(11), self.pad(5))
        )
        style.configure(
            "Accent.TButton", font=self.fonts.button_strong,
            padding=(self.pad(20), self.pad(9)),
        )
        style.configure(
            "TEntry", font=self.fonts.body,
            padding=(self.pad(8), self.pad(6), self.pad(8), self.pad(6)),
        )
        style.configure(
            "TCombobox", font=self.fonts.body,
            padding=(self.pad(8), self.pad(5), self.pad(2), self.pad(5)),
        )
        style.configure("Treeview", font=self.fonts.body)
        style.configure(
            "Treeview", rowheight=int(self.fonts.body.metrics("linespace") * 1.65)
        )
        style.configure("Treeview.Heading", font=self.fonts.caption_strong)

        style.configure(
            "Section.TLabel", font=self.fonts.body_strong, foreground=self.palette["fg"]
        )
        style.configure(
            "Count.TLabel", font=self.fonts.caption, foreground=self.palette["muted"]
        )
        style.configure("Field.TLabel", font=self.fonts.body, foreground=self.palette["fg"])
        style.configure(
            "Hint.TLabel", font=self.fonts.caption, foreground=self.palette["muted"]
        )
        style.configure(
            "Status.TLabel", font=self.fonts.caption, foreground=self.palette["muted"]
        )

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        p = self.palette
        self.titlebar = TitleBar(
            self.root,
            chrome=self.chrome,
            palette=p,
            fonts=self.fonts,
            scale=self.scale,
            title=APP_TITLE,
            on_accent=p["on_accent"],
            on_about=self._show_about,
        )
        self.titlebar.pack(side="top", fill="x")

        divider = tk.Frame(self.root, bg=p["border"], height=1, bd=0, highlightthickness=0)
        divider.pack(side="top", fill="x")

        outer = ttk.Frame(
            self.root,
            padding=(self.pad(20), self.pad(18), self.pad(20), self.pad(16)),
        )
        outer.pack(side="top", fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        self._build_file_section(outer)
        self._build_settings(outer)
        self._build_footer(outer)

        self.chrome.install_resizers()

    def _build_file_section(self, parent: ttk.Frame) -> None:
        p = self.palette
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, self.pad(10)))

        ttk.Label(header, text="文件列表", style="Section.TLabel").pack(side="left")
        self.count_var = tk.StringVar(value="0 个文件")
        ttk.Label(header, textvariable=self.count_var, style="Count.TLabel").pack(
            side="left", padx=(self.pad(10), 0)
        )

        actions = ttk.Frame(header)
        actions.pack(side="right")
        toolbar_style = "Toolbar.TButton"
        self.btn_add = ttk.Button(
            actions, text="添加文件", style=toolbar_style, command=self.add_files
        )
        self.btn_add.pack(side="left", padx=(0, self.pad(6)))
        self.btn_add_folder = ttk.Button(
            actions, text="添加文件夹", style=toolbar_style, command=self.add_folder
        )
        self.btn_add_folder.pack(side="left", padx=(0, self.pad(6)))
        self.btn_remove = ttk.Button(
            actions, text="移除选中", style=toolbar_style, command=self.remove_selected
        )
        self.btn_remove.pack(side="left", padx=(0, self.pad(6)))
        self.btn_clear = ttk.Button(
            actions, text="清空", style=toolbar_style, command=self.clear_files
        )
        self.btn_clear.pack(side="left")

        self._tree_wrap = ttk.Frame(parent)
        self._tree_wrap.grid(row=1, column=0, sticky="nsew")
        self._tree_wrap.rowconfigure(0, weight=1)
        self._tree_wrap.columnconfigure(0, weight=1)

        columns = ("type", "name", "path")
        self.tree = ttk.Treeview(self._tree_wrap, columns=columns, show="headings")
        self.tree.heading("type", text="类型")
        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="路径")
        self.tree.column(
            "type", width=self.pad(72), minwidth=self.pad(60), anchor="center", stretch=False
        )
        self.tree.column(
            "name", width=self.pad(230), minwidth=self.pad(150), anchor="w", stretch=False
        )
        self.tree.column(
            "path", width=self.pad(380), minwidth=self.pad(180), anchor="w", stretch=True
        )
        self.tree.tag_configure("alt", background=p["row_alt"])

        vsb = ttk.Scrollbar(self._tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._sync_actions())

        self._build_empty_state()

    def _build_empty_state(self) -> None:
        p = self.palette
        empty = tk.Frame(self._tree_wrap, bg=p["bg"])
        icon_size = self.pad(52)
        icon = tk.Label(
            empty,
            image=icon_photo(self.root, "empty", icon_size, p["faint"]),
            bg=p["bg"],
            bd=0,
            highlightthickness=0,
        )
        icon.pack(pady=(0, self.pad(10)))
        tk.Label(
            empty,
            text="还没有待转换的文件",
            font=self.fonts.body_strong,
            fg=p["fg"],
            bg=p["bg"],
        ).pack()
        tk.Label(
            empty,
            text="支持视频、音频、图片，可批量添加或按文件夹导入",
            font=self.fonts.caption,
            fg=p["muted"],
            bg=p["bg"],
        ).pack(pady=(self.pad(6), 0))
        self._empty_frame = empty
        self._show_empty()

    def _build_settings(self, parent: ttk.Frame) -> None:
        p = self.palette
        settings = ttk.Frame(parent)
        settings.grid(row=2, column=0, sticky="ew", pady=(self.pad(18), 0))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="输出设置", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, self.pad(10))
        )

        ttk.Label(settings, text="输出文件夹", style="Field.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, self.pad(12))
        )
        self.out_var = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        out_entry = ttk.Entry(settings, textvariable=self.out_var)
        out_entry.grid(row=1, column=1, sticky="ew")
        ttk.Button(settings, text="浏览", command=self.choose_output).grid(
            row=1, column=2, sticky="w", padx=(self.pad(8), 0)
        )

        formats = ttk.Frame(settings)
        formats.grid(row=2, column=0, columnspan=3, sticky="w", pady=(self.pad(12), 0))
        self.img_fmt = tk.StringVar(value="png")
        self.vid_fmt = tk.StringVar(value="mp4")
        self.aud_fmt = tk.StringVar(value="mp3")
        groups = (
            ("图片格式", self.img_fmt, IMAGE_FORMATS),
            ("视频格式", self.vid_fmt, VIDEO_FORMATS),
            ("音频格式", self.aud_fmt, AUDIO_FORMATS),
        )
        for index, (label, var, values) in enumerate(groups):
            cell = ttk.Frame(formats)
            cell.pack(side="left", padx=(0, self.pad(22) if index < 2 else 0))
            ttk.Label(cell, text=label, style="Field.TLabel").pack(
                side="left", padx=(0, self.pad(8))
            )
            ttk.Combobox(
                cell, textvariable=var, values=values, state="readonly", width=7
            ).pack(side="left")

        ttk.Label(settings, text="同名文件会自动重命名，不会覆盖已有文件", style="Hint.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(self.pad(10), 0)
        )

    def _build_footer(self, parent: ttk.Frame) -> None:
        p = self.palette
        separator = tk.Frame(parent, bg=p["border"], height=1, bd=0, highlightthickness=0)
        separator.grid(row=3, column=0, sticky="ew", pady=(self.pad(16), 0))

        footer = ttk.Frame(parent)
        footer.grid(row=4, column=0, sticky="ew", pady=(self.pad(12), 0))

        self.btn_start = ttk.Button(
            footer, text="开始转换", style="Accent.TButton", command=self.start_conversion
        )
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(
            footer, text="停止", command=self.stop_conversion, state="disabled"
        )
        self.btn_stop.pack(side="left", padx=(self.pad(10), 0))

        self.pct_var = tk.StringVar(value="0%")
        ttk.Label(
            footer, textvariable=self.pct_var, style="Status.TLabel", width=5, anchor="e"
        ).pack(side="right")

        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ProgressBar(
            footer,
            width=self.pad(170),
            height=self.pad(6),
            background=p["bg"],
            trough=p["surface_alt"],
            fill=p["accent"],
        )
        self.progress.pack(side="right", padx=(self.pad(10), self.pad(12)))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            footer, textvariable=self.status_var, style="Status.TLabel", anchor="e"
        ).pack(side="right", fill="x", expand=True, padx=(self.pad(12), 0))

    # ---------------------------------------------------------------- 配置
    def _restore_config(self) -> None:
        geometry = self.config.get("window_geometry")
        if not isinstance(geometry, str):
            geometry = None
        maximized = bool(self.config.get("window_maximized", False))
        self.chrome.restore_geometry(geometry, maximized)

        out = self.config.get("output_dir")
        if isinstance(out, str) and out.strip():
            self.out_var.set(out)

        for key, var in (
            ("image_format", self.img_fmt),
            ("video_format", self.vid_fmt),
            ("audio_format", self.aud_fmt),
        ):
            value = self.config.get(key)
            if isinstance(value, str) and value:
                var.set(value)

        self._after_files_changed()

    # ---------------------------------------------------------------- 文件管理
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="选择文件")
        if paths:
            self._batch_add_paths([Path(p) for p in paths])

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择文件夹")
        if not folder:
            return
        paths = [p for p in Path(folder).rglob("*") if p.is_file()]
        self._batch_add_paths(paths)

    def _batch_add_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        added = 0
        before = len(self.files)
        for path in paths:
            self._add_path(path)
        added = len(self.files) - before
        self._after_files_changed()
        if added and not self.converting:
            self._set_status(f"已添加 {added} 个文件")

    def _add_path(self, path: Path) -> None:
        media_type = media_type_of(path)
        if media_type is None:
            return
        key = os.path.normcase(str(path))
        if key in self._file_keys:
            return
        self._file_keys.add(key)
        self.files.append(path)
        iid = self.tree.insert(
            "", "end", values=(_TYPE_LABEL[media_type], path.name, str(path.parent))
        )
        self._item_path[iid] = path

    def remove_selected(self) -> None:
        selected = set(self.tree.selection())
        if not selected:
            return
        remaining: list[Path] = []
        for iid in self.tree.get_children():
            if iid in selected:
                self.tree.delete(iid)
                self._item_path.pop(iid, None)
            else:
                remaining.append(self._item_path[iid])
        removed = len(self.files) - len(remaining)
        self.files = remaining
        self._file_keys = {os.path.normcase(str(p)) for p in remaining}
        self._after_files_changed()
        if not self.converting:
            self._set_status(f"已移除 {removed} 个文件" if removed else "就绪")

    def clear_files(self) -> None:
        self.files.clear()
        self._file_keys.clear()
        self._item_path.clear()
        self.tree.delete(*self.tree.get_children())
        self._after_files_changed()
        if not self.converting:
            self._set_status("就绪")

    def choose_output(self) -> None:
        folder = filedialog.askdirectory(title="选择输出文件夹")
        if folder:
            self.out_var.set(folder)

    def _after_files_changed(self) -> None:
        count = len(self.files)
        self.count_var.set(f"{count} 个文件")
        for index, iid in enumerate(self.tree.get_children()):
            self.tree.item(iid, tags=("alt",) if index % 2 else ())
        if count:
            self._hide_empty()
        else:
            self._show_empty()
        self._sync_actions()

    def _show_empty(self) -> None:
        self._empty_frame.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_empty(self) -> None:
        self._empty_frame.place_forget()

    def _sync_actions(self) -> None:
        self.btn_start.config(state="disabled" if self.converting else "normal")
        self.btn_stop.config(
            state="normal"
            if self.converting and not self.stop_requested
            else "disabled"
        )
        has_files = bool(self.files)
        has_selection = bool(self.tree.selection())
        self.btn_remove.config(state="normal" if has_files and has_selection else "disabled")
        self.btn_clear.config(state="normal" if has_files else "disabled")

    def _set_status(self, text: str) -> None:
        if len(text) > 58:
            text = text[:57] + "…"
        self.status_var.set(text)

    # ---------------------------------------------------------------- 转换流程
    def start_conversion(self) -> None:
        if self.converting:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先添加要转换的文件。")
            return
        raw_out = self.out_var.get().strip()
        if not raw_out:
            messagebox.showwarning("提示", "请设置输出文件夹。")
            return
        out_dir = _resolve_output(raw_out)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("输出文件夹不可用", f"无法创建输出文件夹：\n{exc}")
            return
        if not out_dir.is_dir():
            messagebox.showerror("输出文件夹不可用", "输出路径不是文件夹，请重新选择。")
            return

        self.converting = True
        self.stop_requested = False
        self._sync_actions()
        self.progress_var.set(0)
        self.progress.set(0)
        self.pct_var.set("0%")
        self._set_status("准备转换…")

        # Tk 变量必须在主线程读取，工作线程只拿到值拷贝。
        formats = (self.img_fmt.get(), self.vid_fmt.get(), self.aud_fmt.get())
        worker = threading.Thread(
            target=self._conversion_worker,
            args=(list(self.files), out_dir, formats),
            daemon=True,
        )
        self._worker = worker
        worker.start()

    def stop_conversion(self) -> None:
        if not self.converting or self.stop_requested:
            return
        self.stop_requested = True
        self._set_status("正在停止…")
        self._sync_actions()

    def _conversion_worker(
        self,
        files: list[Path],
        out_dir: Path,
        formats: tuple[str, str, str],
    ) -> None:
        total = max(len(files), 1)
        done = 0
        success = 0
        failed: list[tuple[str, str]] = []
        reserved: set[Path] = set()
        image_tasks: list[tuple[Path, Path]] = []
        ffmpeg_tasks: list[tuple[Path, Path]] = []

        def cancelled() -> bool:
            return self.stop_requested

        try:
            img_fmt, vid_fmt, aud_fmt = formats
            for src in files:
                if cancelled():
                    break
                media_type = media_type_of(src)
                if media_type is None:
                    continue
                target = img_fmt if media_type == "image" else (
                    vid_fmt if media_type == "video" else aud_fmt
                )
                dst = unique_output_path(src, out_dir, target, reserved)
                if media_type == "image":
                    image_tasks.append((src, dst))
                else:
                    ffmpeg_tasks.append((src, dst))

            if image_tasks and not cancelled():
                self.ui_queue.put(("status", f"并行转换 {len(image_tasks)} 张图片…"))
                max_workers = min(len(image_tasks), os.cpu_count() or 2, 8)
                pool = ProcessPoolExecutor(max_workers=max_workers)
                try:
                    futures = {pool.submit(convert_image, s, d): s for s, d in image_tasks}
                    for future in as_completed(futures):
                        if cancelled():
                            try:
                                pool.shutdown(wait=False, cancel_futures=True)
                            except TypeError:
                                pool.shutdown(wait=False)
                            break
                        src = futures[future]
                        try:
                            future.result()
                            success += 1
                        except Exception as exc:
                            failed.append((src.name, str(exc)))
                        done += 1
                        self.ui_queue.put(("file_done", (done, total, src.name)))
                finally:
                    try:
                        pool.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        pool.shutdown(wait=False)

            for src, dst in ffmpeg_tasks:
                if cancelled():
                    break
                self.ui_queue.put(("status", f"正在转换：{src.name}"))

                def on_progress(pct, speed, eta, _name=src.name):
                    if pct is not None:
                        self.ui_queue.put(("file_progress", (done, total, pct, _name)))

                try:
                    convert_ffmpeg(src, dst, on_progress=on_progress, should_cancel=cancelled)
                    success += 1
                except ConversionCancelled:
                    self.ui_queue.put(("status", "已停止"))
                    break
                except Exception as exc:
                    failed.append((src.name, str(exc)))
                    self.ui_queue.put(("status", f"失败：{src.name}"))
                done += 1
                self.ui_queue.put(("file_done", (done, total, src.name)))
        except Exception as exc:
            failed.append(("转换任务", str(exc)))
        finally:
            self.ui_queue.put(("finished", (success, failed, self.stop_requested)))

    def _poll_ui_queue(self) -> None:
        for _ in range(50):
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_message(kind, payload)
        self.root.after(150, self._poll_ui_queue)

    def _handle_message(self, kind: str, payload) -> None:
        if kind == "status":
            self._set_status(payload)
        elif kind == "file_progress":
            done, total, pct, name = payload
            overall = (done + pct / 100.0) / total * 100.0
            self._update_progress(overall)
            self._set_status(f"正在转换：{name}  {pct:.1f}%")
        elif kind == "file_done":
            done, total, _name = payload
            self._update_progress(done / total * 100.0)
        elif kind == "finished":
            self._on_finished(payload)

    def _update_progress(self, value: float) -> None:
        value = max(0.0, min(100.0, value))
        self.progress_var.set(value)
        self.progress.set(value)
        self.pct_var.set(f"{value:.0f}%")

    def _on_finished(self, payload) -> None:
        success, failed, stopped = payload
        self.converting = False
        self.stop_requested = False
        self._worker = None
        self._sync_actions()
        self.progress_var.set(0)
        self.progress.set(0)
        self.pct_var.set("0%")
        if stopped:
            message = f"已停止，完成 {success} 个文件"
            if failed:
                message += f"，失败 {len(failed)} 个"
            self._set_status(message)
            return
        if failed:
            msg = f"完成：成功 {success} 个，失败 {len(failed)} 个。\n\n失败项：\n"
            msg += "\n".join(f"• {n}: {e[:80]}" for n, e in failed[:6])
            self._set_status(f"完成：成功 {success}，失败 {len(failed)}")
            messagebox.showwarning("部分失败", msg)
        else:
            self._set_status(f"全部完成，共 {success} 个文件。")
            messagebox.showinfo("完成", f"已成功转换 {success} 个文件。")

    # ---------------------------------------------------------------- 关闭
    def _show_about(self) -> None:
        messagebox.showinfo(
            "关于 File Converter",
            f"版本号：v{APP_VERSION}\n"
            f"开发日期：{BUILD_DATE}\n"
            f"作者：{AUTHOR}\n"
            f"项目地址：{PROJECT_URL}",
            parent=self.root,
        )

    def _on_close(self) -> None:
        if self.converting:
            if not messagebox.askyesno("退出", "转换仍在进行，确定退出吗？"):
                return
            self.converting = False
            self.stop_requested = True
            worker = self._worker
            if worker is not None and worker.is_alive():
                self._set_status("正在退出…")
                try:
                    self.root.update_idletasks()
                except tk.TclError:
                    pass
                worker.join(timeout=2.0)
        try:
            self.config.set("window_geometry", self.chrome.save_geometry())
            self.config.set("window_maximized", self.chrome.is_maximized())
        except tk.TclError:
            pass
        self.config.set("output_dir", self.out_var.get())
        self.config.set("image_format", self.img_fmt.get())
        self.config.set("video_format", self.vid_fmt.get())
        self.config.set("audio_format", self.aud_fmt.get())
        self.config.save()
        self.root.destroy()
