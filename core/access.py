"""
Access levels — owner and guest.

Guest mode switches on when someone who is not the owner is at the computer
while the owner is away (webcam presence), or when the owner says "lock down".
While it is on, tools that act on the owner's behalf or expose their data are
refused at the dispatcher — the model cannot talk its way past a check it does
not run — and the assistant is told not to share anything personal.

Unlocking is deliberately NOT a voice command: anyone in the room can say
"unlock". It happens when presence recognises the owner's face, or — only if no
face is enrolled — through the on-screen confirm gate (core/confirm.py), which
the model cannot press.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

# Tools that act for the owner, touch their files/accounts, or expose them.
RESTRICTED_TOOLS = frozenset({
    "send_message", "file_controller", "file_processor", "desktop_control",
    "dev_agent", "code_helper", "computer_control", "browser_control",
    "run_protocol", "presence", "security_report", "save_memory", "recall_memory",
    "undo", "shutdown_jarvis", "manage_monitor", "reminder", "game_updater",
    "google_services",
    # the HUD browser's profile is persistent — it holds the owner's logins
    "hud_browser",
})
# computer_settings is mostly harmless (volume, brightness); these are not.
RESTRICTED_SETTINGS = frozenset({
    "restart", "shutdown", "toggle_wifi", "type_text", "press_key", "close_app",
    "open_settings", "file_explorer", "open_run", "task_manager",
})

GUEST_NOTE = (
    "[GUEST_MODE] Someone other than the owner is now at the computer. Until the "
    "owner is back: do not reveal anything from memory or about the owner's life, "
    "files, messages, contacts, schedule or accounts; do not act on their behalf. "
    "General help — questions, search, weather, media, opening apps — is fine. If "
    "asked for something restricted, decline politely in one sentence, without "
    "explaining the security mechanism. Acknowledge this note with nothing."
)
OWNER_NOTE = "[GUEST_MODE_OFF] The owner is back; normal service resumes. Say nothing about this."


class AccessGuard:
    def __init__(self):
        self._lock = threading.Lock()
        self.guest = False
        self.reason = ""
        self.since = 0.0
        self._listeners: list[Callable[[bool, str], None]] = []

    def on_change(self, fn: Callable[[bool, str], None]) -> None:
        self._listeners.append(fn)

    def _emit(self) -> None:
        for fn in list(self._listeners):
            try:
                fn(self.guest, self.reason)
            except Exception as e:
                print(f"[Access] listener failed: {e}")

    def enter_guest(self, reason: str) -> bool:
        with self._lock:
            if self.guest:
                return False
            self.guest, self.reason, self.since = True, reason, time.time()
        print(f"[Access] guest mode ON — {reason}")
        self._emit()
        return True

    def exit_guest(self, reason: str) -> bool:
        with self._lock:
            if not self.guest:
                return False
            self.guest, self.reason = False, reason
        print(f"[Access] guest mode OFF — {reason}")
        self._emit()
        return True

    def check(self, tool: str, args: Optional[dict] = None) -> Optional[str]:
        """None if allowed; otherwise the refusal to hand back to the model."""
        if not self.guest:
            return None
        blocked = tool in RESTRICTED_TOOLS
        if tool == "computer_settings":
            action = str((args or {}).get("action", "")).lower().strip()
            blocked = action in RESTRICTED_SETTINGS or (not action and bool((args or {}).get("description")))
        if not blocked:
            return None
        return (f"[GUEST_MODE] '{tool}' is not available while someone other than the "
                f"owner is at the computer. Decline politely in one short sentence; do "
                f"not mention security systems, cameras or the owner's name.")


_guard: AccessGuard | None = None
_glock = threading.Lock()


def get_guard() -> AccessGuard:
    global _guard
    with _glock:
        if _guard is None:
            _guard = AccessGuard()
        return _guard
