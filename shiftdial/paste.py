"""Save whatever is on the clipboard (a picture or text) as a file in the open Explorer folder."""
from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from shiftdial.utils.paths import Output

_LIST_WINDOWS = ("(New-Object -ComObject Shell.Application).Windows() | ForEach-Object "
                 "{ try { \"$($_.HWND)`t$($_.Document.Folder.Self.Path)\" } catch {} }")


def explorer_folder() -> Path | None:
    """The folder shown in the front-most File Explorer window, or None if no real folder is open."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _LIST_WINDOWS],
                             capture_output=True, text=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    folders: dict[int, Path] = {}
    for line in out.splitlines():
        hwnd, _, folder = line.partition("\t")
        if hwnd.isdigit() and folder and Path(folder).is_dir():  # skips 'This PC' and other virtual places
            folders[int(hwnd)] = Path(folder)
    order: list[int] = []  # EnumWindows walks top-level windows front to back

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int | None, _: int) -> bool:
        order.append(hwnd or 0)
        return True

    ctypes.windll.user32.EnumWindows(collect, 0)
    return next((folders[h] for h in order if h in folders), None)


def save_clipboard(folder: Path) -> Path | None:
    """Write the clipboard's picture (PNG) or text (TXT) into ``folder``; None if it holds neither."""
    clipboard = QGuiApplication.clipboard()
    stem = time.strftime("Clipboard %Y-%m-%d %H%M%S")
    image = clipboard.image()
    if not image.isNull():
        with Output(folder, stem, "png") as out:
            if not image.save(str(out.tmp), "PNG"):
                raise OSError(f"Couldn't write {out.final.name}")
        return out.final
    text = clipboard.text()
    if text:
        with Output(folder, stem, "txt") as out:
            out.tmp.write_text(text, encoding="utf-8")
        return out.final
    return None
