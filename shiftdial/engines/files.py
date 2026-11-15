"""Tools for any file: batch rename, SHA-256, and which apps hold a file open."""
from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any

from shiftdial.engines import JobContext
from shiftdial.utils.paths import Output, split_ext

BAD_CHARS = set('<>:"/\\|?*')


def check_name(name: str) -> None:
    """Raise for a name Windows won't accept as a file name."""
    if not name.strip():
        raise ValueError("New name is empty")
    if BAD_CHARS & set(name) or name.rstrip(" .") != name:
        raise ValueError('Names can\'t contain < > : " / \\ | ? * or end with a space or dot')


def tool_rename(paths: list[Path], p: dict[str, Any], ctx: JobContext) -> list[Path]:
    """One file: 'name.ext'. Several, in name order: 'name 01.ext', 'name 02.ext', ... Never overwrites."""
    name, start = str(p.get("name", "")).strip(), int(p.get("start", 1))
    check_name(name)
    ordered = sorted(paths, key=lambda q: q.name.lower())
    width = len(str(start + len(ordered) - 1))
    outputs: list[Path] = []
    for i, src in enumerate(ordered):
        ctx.check()
        ctx.progress(i / len(ordered), f"Renaming {src.name}")
        ext = "" if src.is_dir() else split_ext(src.name)[1]
        stem = name if len(ordered) == 1 else f"{name} {start + i:0{width}d}"
        dot_ext = f".{ext}" if ext else ""
        dest, n = src.with_name(stem + dot_ext), 1
        while dest.exists() and not dest.samefile(src):  # samefile: a case-only rename is fine
            dest = src.with_name(f"{stem} ({n}){dot_ext}")
            n += 1
        if dest.name != src.name:
            os.rename(src, dest)  # Windows refuses to replace an existing file, so nothing is overwritten
        outputs.append(dest)
    ctx.progress(1.0, "Done")
    return outputs


def sha256(src: Path, ctx: JobContext, done: int, total: int) -> str:
    h = hashlib.sha256()
    with src.open("rb") as f:
        while chunk := f.read(1 << 20):
            ctx.check()
            h.update(chunk)
            done += len(chunk)
            ctx.progress(done / max(total, 1), f"Hashing {src.name}")
    return h.hexdigest()


def tool_hash(paths: list[Path], p: dict[str, Any], ctx: JobContext) -> list[Path]:
    """SHA-256 of each file into '<file>.sha256' (the sha256sum format), and onto the clipboard."""
    total, done = sum(q.stat().st_size for q in paths), 0
    outputs, lines = [], []
    for src in paths:
        digest = sha256(src, ctx, done, total)
        done += src.stat().st_size
        with Output(src.parent, src.name, "sha256") as out:
            out.tmp.write_text(f"{digest} *{src.name}\n", encoding="utf-8")
        outputs.append(out.final)
        lines.append(digest if len(paths) == 1 else f"{digest}  {src.name}")
    ctx.clipboard = "\n".join(lines)
    ctx.progress(1.0, "Done")
    return outputs


class _UniqueProcess(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class _ProcessInfo(ctypes.Structure):  # RM_PROCESS_INFO
    _fields_ = [("Process", _UniqueProcess), ("strAppName", wintypes.WCHAR * 256),
                ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]


def locked_by(paths: list[Path]) -> list[tuple[str, int]]:
    """(app name, process id) of everything holding these files open, via Windows' Restart Manager."""
    rm = ctypes.WinDLL("rstrtmgr")
    session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(33)
    if err := rm.RmStartSession(ctypes.byref(session), 0, key):
        raise OSError(err, "Restart Manager unavailable")
    try:
        files = (wintypes.LPCWSTR * len(paths))(*map(str, paths))
        if err := rm.RmRegisterResources(session, len(paths), files, 0, None, 0, None):
            raise OSError(err, "Can't check these files")
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD()
        while True:
            infos = (_ProcessInfo * max(needed.value, 1))()
            count.value = needed.value
            err = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons))
            if err != 234:  # ERROR_MORE_DATA: the list grew; try again with room for it
                break
        if err:
            raise OSError(err, "Can't list what's using these files")
        return [(infos[i].strAppName, infos[i].Process.dwProcessId) for i in range(count.value)]
    finally:
        rm.RmEndSession(session)


def locks_report(paths: list[Path]) -> str:
    names = ", ".join(p.name for p in paths[:3]) + (" …" if len(paths) > 3 else "")
    try:
        users = locked_by(paths)
    except OSError as e:
        return f"Couldn't check {names}: {e}"
    if not users:
        return f"Nothing is using {names} right now."
    apps = "\n".join(f"{app}  (process {pid})" for app, pid in users)
    return f"{names} is open in:\n\n{apps}\n\nClose it there, then try again."


def same_report(paths: list[Path]) -> str:
    """Which of these files have identical content. Only files of equal size are hashed."""
    by_size: dict[int, list[Path]] = {}
    for f in paths:
        by_size.setdefault(f.stat().st_size, []).append(f)
    groups: list[list[str]] = []
    for files in by_size.values():
        by_hash: dict[str, list[str]] = {}
        for f in files if len(files) > 1 else []:
            with f.open("rb") as fh:
                by_hash.setdefault(hashlib.file_digest(fh, "sha256").hexdigest(), []).append(f.name)
        groups += [names for names in by_hash.values() if len(names) > 1]
    if len(paths) == 2:
        a, b = paths[0].name, paths[1].name
        return f"{a} and {b} are identical." if groups else f"{a} and {b} are different."
    if groups and len(groups[0]) == len(paths):
        return f"All {len(paths)} files are identical."
    if not groups:
        return f"All {len(paths)} files are different."
    return "Identical:\n" + "\n".join("• " + ", ".join(g) for g in groups) + "\n\nThe others are all different."


def tool_same(paths: list[Path], p: dict[str, Any], ctx: JobContext) -> list[Path]:
    # shortcut: the app shows this report in a dialog and never queues it; the CLI prints it as the message
    raise ValueError(same_report(paths))


def tool_lock7z(paths: list[Path], p: dict[str, Any], ctx: JobContext) -> list[Path]:
    """Pack into an AES-256 7Z whose file names are encrypted too."""
    from shiftdial.engines import archive

    password = str(p.get("password", ""))
    if not password:
        raise ValueError("Password is empty")
    return [archive.make(paths, "7z", ctx, password)]


def tool_locks(paths: list[Path], p: dict[str, Any], ctx: JobContext) -> list[Path]:
    # shortcut: the app shows this report in a dialog and never queues it; the CLI prints it as the message
    raise ValueError(locks_report(paths))
