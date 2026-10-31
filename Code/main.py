"""File Converter 入口。"""
from __future__ import annotations
import ctypes
import multiprocessing
import sys

from app import ConverterApp
from dpi import create_root


def _set_app_user_model_id() -> None:
    """给进程一个独立的应用标识，让任务栏使用程序自己的图标与分组。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FileConverter.App")
    except Exception:
        pass


def main() -> None:
    _set_app_user_model_id()
    root, _ = create_root()
    root.withdraw()

    app = ConverterApp(root)
    root.deiconify()
    root.update_idletasks()
    app.chrome.refresh()
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
