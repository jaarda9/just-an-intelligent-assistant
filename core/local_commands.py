"""
Local commands — what still works from the text box when Gemini is
unreachable.

Plain pattern matching for the everyday, unambiguous requests (protocols,
diagnostics, media, volume, opening apps, locking). Each one is turned into
an ordinary tool call and run through the app's dispatcher, so guest mode
still applies. Anything else returns None and the caller says honestly that
it needs the connection.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

RunTool = Callable[[str, dict], str]

_FILLER = re.compile(r"^(?:jarvis[,\s]+)?(?:please\s+|can you\s+|could you\s+)?", re.I)


def _route(t: str) -> Optional[tuple[str, dict]]:
    m = re.match(r"^(?:run|start|initiate|engage|activate|execute)?\s*(?:the\s+)?(.+?)\s+protocol$", t)
    if m:
        return "run_protocol", {"name": m.group(1)}
    if re.search(r"\b(diagnostics?|system check|systems check|status report)\b", t):
        return "run_diagnostics", {}
    if re.search(r"\bwhat'?s playing\b|\bwhat is playing\b|\bwhat song\b", t):
        return "media_control", {"action": "now_playing"}
    m = re.match(r"^(pause|play|resume|stop|next|skip|previous|back)(?:\s+(?:the\s+)?(?:music|song|track|video))?$", t)
    if m:
        act = {"resume": "play", "skip": "next", "back": "previous"}.get(m.group(1), m.group(1))
        return "media_control", {"action": "play_pause" if act in ("play", "pause") else act}
    m = re.match(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?$", t)
    if m:
        return "computer_settings", {"action": "volume_set", "value": str(min(100, int(m.group(1))))}
    if re.match(r"^(?:turn\s+)?(?:the\s+)?volume\s+up$|^louder$", t):
        return "computer_settings", {"action": "volume_up"}
    if re.match(r"^(?:turn\s+)?(?:the\s+)?volume\s+down$|^quieter$", t):
        return "computer_settings", {"action": "volume_down"}
    if re.match(r"^(?:mute|unmute)(?:\s+(?:the\s+)?(?:sound|volume|audio))?$", t):
        return "computer_settings", {"action": "mute"}
    if re.match(r"^lock\s+(?:the\s+)?(?:screen|computer|pc)$", t):
        return "computer_settings", {"action": "lock_screen"}
    if re.match(r"^(?:lock\s*down|lockdown|guest mode)$", t):
        return "access_control", {"action": "lock"}
    m = re.match(r"^(?:open|launch|start)\s+(.+)$", t)
    if m and not m.group(1).endswith("protocol"):
        return "open_app", {"app_name": m.group(1)}
    return None


def route(text: str) -> Optional[tuple[str, dict]]:
    """(tool, args) for a recognised local command, else None."""
    t = _FILLER.sub("", (text or "").strip()).strip(" .!?").lower()
    return _route(t) if t else None


def handle(text: str, run_tool: RunTool) -> Optional[str]:
    """Run a local command; return a short human result, or None if the text
    is not something that can be done without the model."""
    r = route(text)
    if r is None:
        return None
    tool, args = r
    out = str(run_tool(tool, args))
    # Results written for the model end with an instruction; keep the fact.
    for cut in (" Tell the user", " Give the user", " Confirm in", " Summarise in", " Confirm briefly"):
        out = out.split(cut)[0]
    if out.startswith("SYSTEMS DIAGNOSTIC"):
        verdict = [l.strip() for l in out.splitlines()
                   if l.strip().startswith(("All systems nominal", "Attention required"))]
        out = verdict[0] if verdict else "Diagnostics are on screen."
    return out.strip()


OFFLINE_HELP = ("I'm offline right now, so I can only do local commands: run a protocol, "
                "diagnostics, pause / next / what's playing, volume, open an app, lock "
                "the screen, lock down. Everything else returns with the connection.")
