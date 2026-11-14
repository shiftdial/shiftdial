"""%LOCALAPPDATA%\\Shiftdial\\settings.json:
{"theme": "system" | "light" | "dark", "welcomed": bool, "subfolder": bool, "usage": {"webp": 3, ...}}."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from shiftdial.utils.paths import data_dir

THEMES = ("system", "light", "dark")
DEFAULTS: dict[str, Any] = {"theme": "system", "welcomed": False, "subfolder": False, "usage": {}}


def path() -> Path:
    return data_dir() / "settings.json"


def load(file: Path | None = None) -> dict[str, Any]:
    """Settings merged over defaults. A missing, corrupt or hand-edited bad file falls back to defaults."""
    try:
        raw = json.loads((file or path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    s = {**DEFAULTS, "usage": {}}
    if raw.get("theme") in THEMES:
        s["theme"] = raw["theme"]
    for key in ("welcomed", "subfolder"):
        if isinstance(raw.get(key), bool):
            s[key] = raw[key]
    usage = raw.get("usage")
    if isinstance(usage, dict):
        s["usage"] = {k: v for k, v in usage.items() if isinstance(k, str) and type(v) is int and v > 0}
    return s


def save(s: dict[str, Any], file: Path | None = None) -> None:
    """Write via a temp file + replace, so a crash mid-write can't leave half a file."""
    target = file or path()
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    os.replace(tmp, target)
