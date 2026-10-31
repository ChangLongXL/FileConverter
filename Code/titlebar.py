"""自绘标题栏：应用图标、标题、最小化 / 最大化 / 关闭按钮。"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from icons import icon_photo


class CaptionButton(tk.Label):
    """窗口按钮：悬停高亮，关闭按钮使用系统红。"""

    def __init__(
        self,
        master: tk.Misc,
        *,
        icon: str,
        icon_size: int,
        normal_color: str,
        hover_color: str,
        bg: str,
        hover_bg: str,
        pressed_bg: str,
        command,
        width: int,
        height: int,
    ):
        self._icon = icon
        self._icon_size = icon_size
        self._normal_color = normal_color
        self._hover_color = hover_color
        self._normal = icon_photo(master, icon, icon_size, normal_color)
        self._hover = icon_photo(master, icon, icon_size, hover_color)
        super().__init__(
            master,
            image=self._normal,
            bg=bg,
            bd=0,
            highlightthickness=0,
            width=width,
            height=height,
            cursor="arrow",
            takefocus=0,
        )
        self._normal_bg = bg
        self._hover_bg = hover_bg
        self._pressed_bg = pressed_bg
        self._command = command
        self._hovering = False
        self._pressed = False

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_icon(self, icon: str, normal_color: str, hover_color: str) -> None:
        self._icon = icon
        self._normal_color = normal_color
        self._hover_color = hover_color
        self._normal = icon_photo(self, icon, self._icon_size, normal_color)
        self._hover = icon_photo(self, icon, self._icon_size, hover_color)
        self.configure(image=self._hover if self._hovering else self._normal)

    def _on_enter(self, _event=None) -> None:
        self._hovering = True
        if not self._pressed:
            self.configure(bg=self._hover_bg, image=self._hover)

    def _on_leave(self, _event=None) -> None:
        self._hovering = False
        if not self._pressed:
            self.configure(bg=self._normal_bg, image=self._normal)

    def _on_press(self, _event=None) -> None:
        self._pressed = True
        self.configure(bg=self._pressed_bg, image=self._hover)

    def _on_release(self, event) -> None:
        self._pressed = False
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if inside:
            self.configure(bg=self._hover_bg, image=self._hover)
            self._command()
        else:
            self._hovering = False
            self.configure(bg=self._normal_bg, image=self._normal)


class TitleBar(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        chrome,
        palette: dict[str, str],
        fonts,
        scale: float,
        title: str,
        on_accent: str,
        on_about: Callable[[], None],
    ):
        self.height = chrome.titlebar_height
        super().__init__(master, bg=palette["titlebar"], height=self.height)
        self.pack_propagate(False)
        self.palette = palette
        self.fonts = fonts
        self._chrome = chrome
        self._on_about = on_about

        def px(value: float) -> int:
            return int(value * scale)

        drag_area = tk.Frame(self, bg=palette["titlebar"])
        drag_area.pack(side="left", fill="both", expand=True)
        self.drag_area = drag_area

        icon_size = px(20)
        icon = tk.Label(
            drag_area,
            image=icon_photo(master, "app", icon_size, palette["accent"], on_accent),
            bg=palette["titlebar"],
            bd=0,
            highlightthickness=0,
        )
        icon.place(x=px(16), rely=0.5, anchor="w")

        title_label = tk.Label(
            drag_area,
            text=title,
            font=fonts.title,
            fg=palette["fg"],
            bg=palette["titlebar"],
            bd=0,
            highlightthickness=0,
        )
        title_label.place(x=px(16) + icon_size + px(10), rely=0.5, anchor="w")

        for widget in (drag_area, icon, title_label):
            chrome.attach_drag(widget)
            widget.bind("<Button-3>", self._show_context_menu, add="+")

        buttons = tk.Frame(self, bg=palette["titlebar"])
        buttons.pack(side="right", fill="y")

        common = dict(
            icon_size=px(16),
            normal_color=palette["caption_fg"],
            hover_color=palette["caption_hover_fg"],
            bg=palette["titlebar"],
            hover_bg=palette["hover"],
            pressed_bg=palette["pressed"],
            width=px(34),
            height=self.height,
        )
        self._min_button = CaptionButton(
            buttons, icon="minimize", command=chrome.minimize, **common
        )
        self._min_button.pack(side="left")

        self._max_button = CaptionButton(
            buttons, icon="maximize", command=chrome.toggle_maximize, **common
        )
        self._max_button.pack(side="left")

        self._close_button = CaptionButton(
            buttons,
            icon="close",
            normal_color=palette["caption_fg"],
            hover_color="#ffffff",
            bg=palette["titlebar"],
            hover_bg=palette["danger"],
            pressed_bg=palette["danger_pressed"],
            command=chrome.close,
            icon_size=px(16),
            width=px(34),
            height=self.height,
        )
        self._close_button.pack(side="left")

        chrome.caption_width = px(34) * 3
        chrome.on_maximize_change = self.set_maximized

        self._scale = scale
        self._menu_parent = self.winfo_toplevel()
        self._menu: tk.Canvas | None = None
        self._menu_size = (0, 0)
        self._menu_visible = False
        self._menu_rows: dict[int, tuple[int, int, bool, Callable[[], None]]] = {}

    def _px(self, value: float) -> int:
        return int(value * self._scale)

    def _menu_items(self):
        chrome = self._chrome
        maximized = chrome.is_maximized()
        return (
            ("还原", chrome.restore, maximized),
            ("最小化", chrome.minimize, True),
            ("最大化", chrome.maximize, not maximized),
            None,
            ("关闭", chrome.close, True),
            None,
            ("关于", self._on_about, True),
        )

    def _draw_context_menu(self) -> None:
        palette = self.palette
        menu = self._menu
        if menu is None:
            menu = tk.Canvas(
                self._menu_parent,
                bg=palette["surface"],
                bd=0,
                highlightthickness=1,
                highlightbackground=palette["border_strong"],
                highlightcolor=palette["border_strong"],
                takefocus=0,
            )
            self._menu = menu
        menu.delete("all")
        self._menu_rows = {}

        items = self._menu_items()
        texts = [item[0] for item in items if item is not None]
        text_width = max(self.fonts.body.measure(text) for text in texts)
        width = max(self._px(150), text_width + self._px(56))
        item_h = self._px(30)
        sep_h = self._px(9)
        height = sum(item_h if item else sep_h for item in items) + self._px(10)
        menu.configure(width=width, height=height, cursor="arrow")
        self._menu_size = (width, height)

        y = self._px(5)
        for index, item in enumerate(items):
            if item is None:
                menu.create_line(
                    self._px(10), y + sep_h // 2,
                    width - self._px(10), y + sep_h // 2,
                    fill=palette["border_strong"],
                )
                y += sep_h
                continue
            label, command, enabled = item
            tag = f"row{index}"
            rect = menu.create_rectangle(
                1, y, width - 1, y + item_h,
                fill=palette["surface"], outline="", tags=(tag,),
            )
            text = menu.create_text(
                self._px(16), y + item_h // 2,
                text=label, anchor="w", font=self.fonts.body,
                fill=palette["fg"] if enabled else palette["faint"],
                tags=(tag,),
            )
            self._menu_rows[index] = (rect, text, enabled, command)
            if enabled:
                menu.tag_bind(tag, "<Enter>", lambda _e, i=index: self._menu_hover(i, True))
                menu.tag_bind(tag, "<Leave>", lambda _e, i=index: self._menu_hover(i, False))
                menu.tag_bind(tag, "<Button-1>", lambda _e, i=index: self._menu_invoke(i))
            y += item_h

    def _menu_hover(self, index: int, inside: bool) -> None:
        row = self._menu_rows.get(index)
        if row is None or self._menu is None:
            return
        rect, text, enabled, _command = row
        if not enabled:
            return
        self._menu.itemconfigure(
            rect, fill=self.palette["accent"] if inside else self.palette["surface"]
        )
        self._menu.itemconfigure(
            text, fill=self.palette["on_accent"] if inside else self.palette["fg"]
        )
        self._menu.configure(cursor="hand2" if inside else "arrow")

    def _menu_invoke(self, index: int) -> None:
        row = self._menu_rows.get(index)
        if row is None or not row[2]:
            return
        self._hide_context_menu()
        row[3]()

    def _show_context_menu(self, event: tk.Event) -> str:
        self._hide_context_menu()
        self._draw_context_menu()
        menu = self._menu
        root = self._menu_parent
        if menu is None:
            return "break"

        width, height = self._menu_size
        x = event.x_root - root.winfo_rootx() + self._px(2)
        y = event.y_root - root.winfo_rooty() + self._px(2)
        max_x = max(self._px(4), root.winfo_width() - width - self._px(4))
        max_y = max(self._px(4), root.winfo_height() - height - self._px(4))
        x = min(max(x, self._px(4)), max_x)
        y = min(max(y, self._px(4)), max_y)

        menu.place(x=x, y=y)
        menu.tk.call("raise", menu._w)
        self._menu_visible = True
        root.bind_all("<Button-1>", self._on_global_click, add="+")
        root.bind_all("<Escape>", self._on_escape, add="+")
        root.bind("<FocusOut>", self._on_menu_focus_out, add="+")
        return "break"

    def _hide_context_menu(self) -> None:
        if not self._menu_visible:
            return
        self._menu_visible = False
        root = self._menu_parent
        try:
            if self._menu is not None:
                self._menu.place_forget()
            root.unbind_all("<Button-1>")
            root.unbind_all("<Escape>")
            root.unbind("<FocusOut>")
        except tk.TclError:
            pass

    def _on_global_click(self, _event: tk.Event) -> None:
        if self._menu_visible:
            self._hide_context_menu()

    def _on_escape(self, _event: tk.Event) -> str:
        self._hide_context_menu()
        return "break"

    def _on_menu_focus_out(self, _event: tk.Event) -> None:
        if self._menu_visible:
            self._hide_context_menu()

    def set_maximized(self, maximized: bool) -> None:
        self._max_button.set_icon(
            "restore" if maximized else "maximize",
            self.palette["caption_fg"],
            self.palette["caption_hover_fg"],
        )
