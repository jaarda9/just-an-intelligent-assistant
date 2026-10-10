"""
Protocol storage and validation — one place that reads and writes
config/protocols.json for the HUD editor (and anything else that edits it).

The run side stays in plugins/protocols.py; this module only owns the file
format: what a valid protocol, step and trigger look like.
"""
from __future__ import annotations

import json
import re

from core.triggers import DAYS, _valid_time

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,39}$")
FORBIDDEN_TOOLS = {"run_protocol"}
EVENTS = ("arrive", "leave", "startup")


def _path():
    from plugins.protocols import PROTOCOLS_PATH
    return PROTOCOLS_PATH


def load_all() -> dict:
    """Every protocol (creating the starter file on first use)."""
    from plugins.protocols import _load
    return _load()


def _raw() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def validate(name: str, proto: dict) -> list[str]:
    """Problems with one protocol, as sentences; empty when valid."""
    errs = []
    if not _NAME_RE.match(name or ""):
        errs.append("Name: lowercase letters, digits, spaces, - or _, up to 40 characters.")
    steps = proto.get("steps")
    if not isinstance(steps, list) or not steps:
        errs.append("Add at least one step.")
        steps = []
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            errs.append(f"Step {i} is not valid.")
        elif "wait" in s:
            try:
                if not 0 < float(s["wait"]) <= 30:
                    raise ValueError
            except (TypeError, ValueError):
                errs.append(f"Step {i}: wait must be 0–30 seconds.")
        elif not s.get("tool"):
            errs.append(f"Step {i}: choose a tool.")
        elif s["tool"] in FORBIDDEN_TOOLS:
            errs.append(f"Step {i}: a protocol cannot start another protocol.")
        elif not isinstance(s.get("args", {}), dict):
            errs.append(f"Step {i}: arguments are not valid.")
    for i, t in enumerate(proto.get("triggers") or [], 1):
        if "at" in t:
            if not _valid_time(t["at"]):
                errs.append(f"Trigger {i}: time must be HH:MM.")
            bad = [d for d in t.get("days") or [] if d not in DAYS]
            if bad:
                errs.append(f"Trigger {i}: unknown day {bad[0]!r}.")
        elif t.get("on") not in EVENTS:
            errs.append(f"Trigger {i}: unknown event.")
    return errs


def save(name: str, proto: dict, old_name: str | None = None) -> list[str]:
    """Validate and write one protocol (renaming if old_name differs).
    Returns the problems; nothing is written unless the list is empty."""
    name = (name or "").strip().lower()
    clean = {
        "aliases": [a.strip().lower() for a in proto.get("aliases") or [] if a.strip()],
        "announce": (proto.get("announce") or "").strip(),
        "steps": proto.get("steps") or [],
    }
    if proto.get("triggers"):
        clean["triggers"] = proto["triggers"]
    errs = validate(name, clean)
    data = _raw()
    if old_name != name and name in data:
        errs.append(f"A protocol called '{name}' already exists.")
    if errs:
        return errs
    if old_name and old_name != name:
        data.pop(old_name, None)
    data[name] = clean
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return []


def delete(name: str) -> bool:
    data = _raw()
    if name not in data:
        return False
    del data[name]
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def step_summary(step: dict) -> str:
    if "wait" in step:
        return f"wait {step['wait']} s"
    args = step.get("args") or {}
    shown = ", ".join(f"{k}={v}" for k, v in args.items() if v not in ("", None))
    return f"{step.get('tool', '?')}" + (f"  ({shown})" if shown else "")


# Used when the assistant is not running yet (the live catalogue comes from
# the tool registries via MainWindow.get_tool_catalog).
FALLBACK_CATALOG = [
    {"name": "open_app", "description": "Open an application",
     "params": {"app_name": "Exact name of the application"}},
    {"name": "computer_settings", "description": "Volume, brightness, windows, keys…",
     "params": {"action": "e.g. volume_set, mute, brightness_down, lock_screen",
                "value": "Optional value, e.g. volume level 0-100"}},
    {"name": "run_diagnostics", "description": "Full systems check", "params": {}},
    {"name": "weather_report", "description": "Weather report", "params": {}},
    {"name": "web_search", "description": "Search the web",
     "params": {"query": "What to search for", "mode": "search | news | research"}},
    {"name": "youtube_video", "description": "Play a YouTube video",
     "params": {"query": "What to play"}},
]
