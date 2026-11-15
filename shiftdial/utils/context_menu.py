"""Explorer right-click entries ("Show more options" on Windows 11), per user under HKCU\\Software\\Classes.

Only for the zip build: a Store (MSIX) app's registry writes stay in its private copy, and Windows 11's
compact menu needs a native shell extension.
"""
from __future__ import annotations

import winreg

from shiftdial.utils import startup

ROOT = r"Software\Classes"
# (registry class, verb key, menu text, dial mode)
VERBS = [("*", "Shiftdial.Convert", "Convert with Shiftdial", "formats"),
         ("*", "Shiftdial.Tools", "Shiftdial tools", "tools"),
         ("Directory", "Shiftdial.Tools", "Shiftdial tools", "tools")]


def available() -> bool:
    return startup.command() is not None and not startup.packaged()


def _key(root: str, cls: str, verb: str) -> str:
    return rf"{root}\{cls}\shell\{verb}"


def is_enabled(root: str = ROOT) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key(root, *VERBS[0][:2]) + r"\command") as k:
            return winreg.QueryValue(k, None).startswith(startup.command() or "\0")
    except OSError:
        return False


def set_enabled(on: bool, root: str = ROOT) -> None:
    exe = startup.command()
    if exe is None:
        raise RuntimeError("The right-click menu needs the built Shiftdial.exe")
    for cls, verb, text, mode in VERBS:
        key = _key(root, cls, verb)
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, text)
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, exe)
                winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")  # one entry for many files
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'{exe} --dial {mode} "%1"')
        else:
            for sub in (key + r"\command", key):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except FileNotFoundError:
                    pass
