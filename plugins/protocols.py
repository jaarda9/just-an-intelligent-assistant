"""
Protocols — named, multi-step routines in the style of "House Party Protocol".

A protocol is a list of ordinary tool calls (any action or plugin JARVIS has)
stored in config/protocols.json. Saying "initiate work protocol" runs each step
in order through the app's own dispatcher (player.run_tool), so the sequence is
deterministic — it does not depend on the model remembering every step.

The file is re-read on every call: edit it while the app is running and the
next request uses the new version. A starter file is written on first use.
"""
import difflib
import json
import re
import time
from pathlib import Path

PROTOCOLS_PATH = Path(__file__).resolve().parent.parent / "config" / "protocols.json"

# A protocol may not start another protocol: one typo in the file would
# otherwise be an infinite loop the user can only stop by killing the app.
_FORBIDDEN_STEP_TOOLS = {"run_protocol"}
_MAX_WAIT = 30.0

_STARTER = {
    "_readme": (
        "Each protocol: optional 'aliases' (other names it answers to), "
        "optional 'announce' (what JARVIS says it is doing), and 'steps'. "
        "A step is {\"tool\": <any tool name>, \"args\": {...}} or {\"wait\": <seconds>}. "
        "Tool names and arguments are the same ones JARVIS uses — e.g. open_app "
        "{app_name}, computer_settings {action, value}, browser_control, "
        "youtube_video, desktop_control, weather_report, run_diagnostics."
    ),
    "work": {
        "aliases": ["work mode", "focus", "focus mode"],
        "announce": "Work protocol engaged.",
        "steps": [
            {"tool": "computer_settings", "args": {"action": "volume_set", "value": "25"}},
            {"tool": "open_app", "args": {"app_name": "Visual Studio Code"}},
            {"wait": 1},
            {"tool": "open_app", "args": {"app_name": "Spotify"}},
        ],
    },
    "night": {
        "aliases": ["good night", "goodnight", "night mode", "bedtime"],
        "announce": "Good night protocol. Powering down the room.",
        "steps": [
            {"tool": "computer_settings", "args": {"action": "mute"}},
            {"tool": "computer_settings", "args": {"action": "brightness_down"}},
            {"wait": 1},
            {"tool": "computer_settings", "args": {"action": "lock_screen"}},
        ],
    },
    "status": {
        "aliases": ["morning", "sitrep"],
        "announce": "Running the morning status sweep.",
        "steps": [
            {"tool": "run_diagnostics", "args": {}},
            {"tool": "weather_report", "args": {}},
        ],
    },
}


PLUGIN = {
    "name": "run_protocol",
    "description": (
        "Runs a named PROTOCOL: a saved multi-step routine the user defined "
        "(e.g. 'initiate work protocol', 'engage night mode', 'house party "
        "protocol'). Call this whenever the user names a protocol or mode they "
        "have set up — do NOT perform the individual steps yourself. Use "
        "action='list' when the user asks which protocols exist."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": "Protocol name as the user said it, in English, without the word 'protocol' (e.g. 'work', 'night', 'house party').",
            },
            "action": {
                "type": "STRING",
                "description": "'run' (default) or 'list'.",
            },
        },
        "required": [],
    },
}


def _load() -> dict:
    if not PROTOCOLS_PATH.exists():
        PROTOCOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROTOCOLS_PATH.write_text(json.dumps(_STARTER, indent=2), encoding="utf-8")
    data = json.loads(PROTOCOLS_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)}


def _norm(text: str) -> str:
    text = re.sub(r"\b(protocol|mode|initiate|engage|activate|run|start)\b", " ",
                  str(text or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _find(protocols: dict, wanted: str) -> str | None:
    want = _norm(wanted)
    if not want:
        return None
    names: dict[str, str] = {}
    for key, proto in protocols.items():
        names[_norm(key)] = key
        for alias in proto.get("aliases", []) or []:
            names[_norm(alias)] = key
    if want in names:
        return names[want]
    close = difflib.get_close_matches(want, list(names), n=1, cutoff=0.75)
    return names[close[0]] if close else None


def _failed(result: str) -> bool:
    r = str(result or "").lower()
    return r.startswith(("unknown tool", "tool '", "action '", "plugin '", "failed")) \
        or " failed" in r[:80] or "error:" in r[:80]


def _log(player, text: str) -> None:
    if player:
        try:
            player.write_log(f"JARVIS: {text}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        protocols = _load()
    except Exception as e:
        return f"I could not read config/protocols.json — the file is not valid JSON ({e})."

    action = str(parameters.get("action") or "run").lower().strip()
    if action == "list" or not parameters.get("name"):
        if not protocols:
            return "No protocols are defined yet. They live in config/protocols.json."
        lines = []
        for key, proto in protocols.items():
            aliases = ", ".join(proto.get("aliases", []) or [])
            lines.append(f"{key} ({len(proto.get('steps', []))} steps)"
                         + (f" — also: {aliases}" if aliases else ""))
        return "Protocols on file: " + "; ".join(lines) + "."

    key = _find(protocols, parameters["name"])
    if key is None:
        return (f"There is no protocol called '{parameters['name']}'. "
                f"On file: {', '.join(protocols) or 'none'}.")

    run_tool = getattr(player, "run_tool", None) if player else None
    if not callable(run_tool):
        return "Protocols need the main app's tool dispatcher, which is not available here."

    proto = protocols[key]
    steps = proto.get("steps", []) or []
    _log(player, f"Protocol '{key}' — {len(steps)} steps")

    try:
        from core.tasks import get_board
        board = get_board()
    except Exception:
        board = None

    done, failures = 0, []
    for i, step in enumerate(steps, 1):
        if board is not None:
            label = "wait" if isinstance(step, dict) and "wait" in step else \
                (step.get("tool", "?") if isinstance(step, dict) else "?")
            board.update(progress=(i - 1) / max(1, len(steps)),
                         detail=f"{key} · step {i}/{len(steps)}: {label}", name="Protocol")
        if not isinstance(step, dict):
            failures.append(f"step {i}: not a valid step")
            continue
        if "wait" in step:
            try:
                time.sleep(max(0.0, min(float(step["wait"]), _MAX_WAIT)))
            except (TypeError, ValueError):
                pass
            continue
        tool = str(step.get("tool") or "").strip()
        if not tool or tool in _FORBIDDEN_STEP_TOOLS:
            failures.append(f"step {i}: '{tool or '?'}' cannot be used in a protocol")
            continue
        try:
            result = run_tool(tool, step.get("args") or {})
        except Exception as e:
            result = f"failed: {e}"
        if _failed(result):
            failures.append(f"step {i} ({tool}): {str(result)[:100]}")
        else:
            done += 1

    total = sum(1 for s in steps if isinstance(s, dict) and "wait" not in s)
    announce = proto.get("announce") or f"{key.title()} protocol complete."
    summary = f"[PROTOCOL {key}] {done}/{total} steps succeeded."
    if failures:
        summary += " Problems: " + " | ".join(failures)
    _log(player, summary)
    if player is not None and hasattr(player, "notify"):
        try:
            player.notify(f"{key} protocol",
                          f"{done}/{total} steps complete" + (f" · {len(failures)} failed" if failures else ""),
                          "warn" if failures else "ok")
        except Exception:
            pass
    return (f"{summary} Tell the user, in one short sentence in their language, "
            f"in the spirit of: \"{announce}\"" + (" — and name what failed." if failures else "."))
