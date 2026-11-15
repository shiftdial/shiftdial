"""%LOCALAPPDATA%\\Shiftdial\\settings.json:
{"theme": "system" | "light" | "dark", "dial_keys": [16], "tools_keys": [17, 16], "welcomed": bool,
 "subfolder": bool, "notify": bool, "usage": {"webp": 3, ...}}   (keys are Windows virtual-key codes)"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from shiftdial.utils.paths import data_dir

THEMES = ("system", "light", "dark")
NOT_ALLOWED_KEYS = {0x01, 0x02, 0x04, 0x1B}  # mouse buttons (they do the dragging) and Esc (it cancels)
DEFAULTS: dict[str, Any] = {"theme": "system", "dial_keys": [0x10], "tools_keys": [0x11, 0x10],
                            "welcomed": False, "subfolder": False, "notify": True, "usage": {}}


def valid_keys(v: Any) -> bool:
    """1-3 distinct keyboard keys."""
    return (isinstance(v, list) and 1 <= len(v) <= 3 and len(set(v)) == len(v)
            and all(type(k) is int and 0 < k < 255 and k not in NOT_ALLOWED_KEYS for k in v))


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
    s = {**DEFAULTS, "usage": {}, "dial_keys": list(DEFAULTS["dial_keys"]), "tools_keys": list(DEFAULTS["tools_keys"])}
    if raw.get("theme") in THEMES:
        s["theme"] = raw["theme"]
    for key in ("dial_keys", "tools_keys"):
        if valid_keys(raw.get(key)):
            s[key] = raw[key]
    if set(s["dial_keys"]) == set(s["tools_keys"]):  # one combo can't open both dials
        s["dial_keys"], s["tools_keys"] = list(DEFAULTS["dial_keys"]), list(DEFAULTS["tools_keys"])
    for key in ("welcomed", "subfolder", "notify"):
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
