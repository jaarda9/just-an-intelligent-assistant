"""
Protocol triggers — protocols that run themselves.

A protocol in config/protocols.json may carry a "triggers" list:

    "work": {
      "steps": [...],
      "triggers": [
        {"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        {"on": "arrive"}
      ]
    }

  {"at": "HH:MM", "days": [...]}   once a day at that minute (days optional = every day)
  {"on": "arrive"} / {"on": "leave"}   webcam presence sees the owner come back / go
  {"on": "startup"}                 once, when the assistant comes online

Firing goes through the app's own dispatcher (run_tool("run_protocol", ...)),
so guest mode still applies: a trigger that fires while a stranger is at the
desk is refused like any other request. Time triggers record the date they
last fired in config/trigger_state.json, so a restart inside the same minute
never fires twice.
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
from pathlib import Path
from typing import Callable

STATE_PATH = Path(__file__).resolve().parent.parent / "config" / "trigger_state.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TICK_S = 20.0


def _load_protocols() -> dict:
    try:
        from plugins.protocols import _load
        return _load()
    except Exception:
        return {}


def _valid_time(s: str) -> bool:
    try:
        _dt.datetime.strptime(str(s), "%H:%M")
        return True
    except ValueError:
        return False


def describe(trigger: dict) -> str:
    """Human wording for a trigger (HUD editor, status answers)."""
    if "at" in trigger:
        days = trigger.get("days") or []
        when = "every day" if not days or set(days) == set(DAYS) else \
            "weekdays" if set(days) == set(DAYS[:5]) else \
            "weekends" if set(days) == set(DAYS[5:]) else ", ".join(d.title() for d in days)
        return f"at {trigger['at']} {when}"
    return {"arrive": "when you sit down", "leave": "when you leave",
            "startup": "when JARVIS starts"}.get(trigger.get("on", ""), "unknown trigger")


class TriggerEngine:
    def __init__(self, run_protocol: Callable[[str, str], None],
                 now: Callable[[], _dt.datetime] = _dt.datetime.now):
        """run_protocol(name, reason) does the actual run (on this thread)."""
        self._run = run_protocol
        self._now = now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fired: dict[str, str] = self._load_state()

    # ── state ────────────────────────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._fired, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"[Triggers] could not save state: {e}")

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="protocol-triggers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"[Triggers] tick failed: {e}")
            self._stop.wait(TICK_S)

    # ── firing ───────────────────────────────────────────────────────────────
    def tick(self) -> list[str]:
        """Fire every time trigger whose minute has come and has not fired
        today. Returns the protocols fired (for tests and logs)."""
        now = self._now()
        today, hhmm, dow = now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), DAYS[now.weekday()]
        fired = []
        for name, proto in _load_protocols().items():
            for i, trig in enumerate(proto.get("triggers") or []):
                at = trig.get("at")
                if not at or not _valid_time(at):
                    continue
                days = [d.lower()[:3] for d in (trig.get("days") or DAYS)]
                if dow not in days:
                    continue
                key = f"{name}#{i}#{at}"
                # Due if the minute has arrived (and not more than 10 min ago,
                # so starting the app at noon does not run the 9:00 routine).
                due = at <= hhmm <= _plus_minutes(at, 10)
                if due and self._fired.get(key) != today:
                    self._fired[key] = today
                    self._save_state()
                    fired.append(name)
                    self._run(name, f"scheduled {describe(trig)}")
        return fired

    def fire_event(self, event: str) -> list[str]:
        """'arrive' / 'leave' / 'startup' — run every protocol bound to it."""
        fired = []
        for name, proto in _load_protocols().items():
            for trig in proto.get("triggers") or []:
                if trig.get("on") == event:
                    fired.append(name)
                    self._run(name, describe(trig))
                    break
        return fired


def _plus_minutes(hhmm: str, minutes: int) -> str:
    t = _dt.datetime.strptime(hhmm, "%H:%M") + _dt.timedelta(minutes=minutes)
    return "23:59" if t.day != 1 else t.strftime("%H:%M")
