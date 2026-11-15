"""Detect "dragging files from Explorer + Shift" and tell the GUI."""
from __future__ import annotations

import ctypes
import logging
import math
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202

VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL, VK_ESCAPE, VK_F8, VK_F9 = 0x10, 0x11, 0x12, 0x14, 0x1B, 0x77, 0x78
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
_GENERIC = {VK_LSHIFT: VK_SHIFT, VK_RSHIFT: VK_SHIFT, VK_LCONTROL: VK_CONTROL, VK_RCONTROL: VK_CONTROL,
            VK_LMENU: VK_MENU, VK_RMENU: VK_MENU}
DIAL_KEYS, TOOLS_KEYS = (VK_SHIFT,), (VK_CONTROL, VK_SHIFT)  # defaults; Settings can record any keys
FIXED = (VK_F8, VK_F9, VK_ESCAPE)  # always watched: F8 formats, F9 tools, Esc closes
NOT_ALLOWED = {VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_ESCAPE}  # mouse buttons drag; Esc cancels
_NAMES = {VK_SHIFT: "Shift", VK_CONTROL: "Ctrl", VK_MENU: "Alt", VK_CAPITAL: "Caps Lock", 0x09: "Tab", 0x20: "Space",
          0x5B: "Win", 0x5C: "Win", 0x08: "Backspace", 0x0D: "Enter", 0x2D: "Insert", 0x2E: "Delete"}
_MODIFIER_ORDER = (VK_CONTROL, VK_MENU, VK_SHIFT)


def normal(vk: int) -> int:
    """Left/right Shift, Ctrl and Alt count as the same key."""
    return _GENERIC.get(vk, vk)


def key_name(vk: int) -> str:
    if vk in _NAMES:
        return _NAMES[vk]
    buf = ctypes.create_unicode_buffer(32)
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    if scan and ctypes.windll.user32.GetKeyNameTextW(scan << 16, buf, len(buf)):
        return buf.value.title() if len(buf.value) > 1 else buf.value
    return f"Key {vk}"


def keys_label(keys: tuple[int, ...] | list[int]) -> str:
    """'Ctrl + Shift', modifiers first, the way Windows writes shortcuts."""
    order = sorted(keys, key=lambda k: (_MODIFIER_ORDER.index(k) if k in _MODIFIER_ORDER else 9, k))
    return " + ".join(key_name(k) for k in order)

DRAG_THRESHOLD_PX = 8
POLL_S = 0.008


class DragDetector:
    """Tracks "left button held and moved > 8 px" plus keys, and emits:"""

    def __init__(self, emit: Callable[[str], None], is_file_source: Callable[[int, int], bool]) -> None:
        self._emit = emit
        self._is_file_source = is_file_source
        self._down_at: tuple[int, int] | None = None
        self._dragging = False
        self._source_ok = False
        self._keys: set[int] = set()
        self.dial_keys: frozenset[int] = frozenset(DIAL_KEYS)  # all held → formats dial
        self.tools_keys: frozenset[int] = frozenset(TOOLS_KEYS)  # all held → tools dial

    def mouse(self, msg: int, x: int, y: int) -> None:
        if msg == WM_LBUTTONDOWN:
            self._down_at, self._dragging = (x, y), False
        elif msg == WM_MOUSEMOVE and self._down_at and not self._dragging:
            if math.dist(self._down_at, (x, y)) > DRAG_THRESHOLD_PX:
                self._dragging = True
                self._source_ok = self._is_file_source(*self._down_at)
                self._trigger()
        elif msg == WM_LBUTTONUP:
            if self._dragging and self._source_ok:
                self._emit("end")
            self._down_at, self._dragging = None, False

    def key(self, msg: int, vk: int) -> None:
        vk = normal(vk)
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            fresh = vk not in self._keys  # held keys auto-repeat KEYDOWN; act only on the first
            self._keys.add(vk)
            if fresh and self._dragging and self._source_ok:
                if vk == VK_ESCAPE:
                    self._emit("dismiss")
                elif vk in self.dial_keys | self.tools_keys or vk in (VK_F8, VK_F9):
                    self._trigger()
        elif msg in (WM_KEYUP, WM_SYSKEYUP):
            self._keys.discard(vk)  # releasing Shift leaves the wheel up

    def _trigger(self) -> None:
        if not (self._dragging and self._source_ok):
            return
        # When both combos are held (Shift inside Ctrl + Shift), the one with more keys wins.
        held = [(len(keys), mode) for keys, mode in ((self.tools_keys, "tools"), (self.dial_keys, "formats"))
                if keys <= self._keys]
        if VK_F9 in self._keys:
            self._emit("tools")
        elif held:
            self._emit(max(held)[1])
        elif VK_F8 in self._keys:
            self._emit("formats")


class InputPoller:
    """Turns polled input *state* into the detector's down/move/up and key events (unit-tested)."""

    def __init__(self, detector: DragDetector) -> None:
        self._detector = detector
        self._pressed = False
        self._keys: set[int] = set()

    @property
    def pressed(self) -> bool:
        return self._pressed

    def feed(self, button_down: bool, x: int, y: int, keys_down: set[int]) -> None:
        if button_down != self._pressed:
            self._pressed = button_down
            self._detector.mouse(WM_LBUTTONDOWN if button_down else WM_LBUTTONUP, x, y)
        elif button_down:
            self._detector.mouse(WM_MOUSEMOVE, x, y)
        for vk in keys_down - self._keys:
            self._detector.key(WM_KEYDOWN, vk)
        for vk in self._keys - keys_down:
            self._detector.key(WM_KEYUP, vk)
        self._keys = set(keys_down)


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GA_ROOT = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SM_SWAPBUTTON = 23

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def is_explorer_at(x: int, y: int) -> bool:
    """True if the window under (x, y) belongs to explorer.exe (folders or the desktop)."""
    hwnd = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), GA_ROOT)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return False
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return False
        return Path(buf.value).name.lower() == "explorer.exe"
    finally:
        kernel32.CloseHandle(handle)


def _is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# Polled rather than hooked: a low-level hook puts every mouse move on the PC behind this process
# (and Python's GIL), which made the cursor lag whenever a conversion was busy.
class DragHooks(QObject):
    """Polls input on its own thread. ``event`` is queued to the GUI thread by Qt."""

    event = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._detector = DragDetector(self.event.emit, is_explorer_at)
        self._poller = InputPoller(self._detector)
        self._stop = threading.Event()
        self._watched = (*DIAL_KEYS, *TOOLS_KEYS, *FIXED)  # GetAsyncKeyState on Shift/Ctrl/Alt covers both sides

    def set_keys(self, dial: list[int], tools: list[int]) -> None:
        """The key combos for each dial. Attribute swaps only, so the polling thread needs no lock."""
        self._detector.dial_keys, self._detector.tools_keys = frozenset(dial), frozenset(tools)
        self._watched = tuple({*dial, *tools, *FIXED})

    def start(self) -> None:
        threading.Thread(target=self._run, name="drag-watch", daemon=True).start()
        log.info("drag watcher started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        pt = wintypes.POINT()
        while not self._stop.wait(POLL_S):
            try:
                # The "left" button is the primary one; with swapped mouse buttons that's the right.
                primary = VK_RBUTTON if user32.GetSystemMetrics(SM_SWAPBUTTON) else VK_LBUTTON
                down = _is_down(primary)
                if not down and not self._poller.pressed:
                    continue
                user32.GetCursorPos(ctypes.byref(pt))
                keys = {vk for vk in self._watched if _is_down(vk)}
                self._poller.feed(down, pt.x, pt.y, keys)
            except Exception:  # noqa: BLE001 - keep watching; one bad tick mustn't stop detection
                log.exception("drag watcher")
