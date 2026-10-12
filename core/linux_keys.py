"""
System-wide keys on Linux, for the summon hotkey and push-to-talk.

X11 lets any program watch the keyboard, and `pynput` (optional) does it from
a background thread, so both chords work while another window has focus.
Wayland deliberately allows no such thing: there, and whenever pynput is not
installed, callers fall back to binding the chord inside JARVIS's own window
(scope "window") and say so.
"""
from __future__ import annotations

import os
import platform


def session_type() -> str:
    """'x11', 'wayland' or '' (not Linux / unknown)."""
    if platform.system() != "Linux":
        return ""
    st = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if st in ("x11", "wayland"):
        return st
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else ""


def global_keys_available() -> bool:
    """True when a system-wide key hook can work here (Linux on X11 with
    pynput installed)."""
    if session_type() != "x11":
        return False
    try:
        import pynput.keyboard  # noqa: F401
        return True
    except Exception:
        return False


def _keymap():
    from pynput.keyboard import Key
    return {
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
        "alt": {Key.alt, Key.alt_l, Key.alt_r, getattr(Key, "alt_gr", Key.alt)},
        "space": {Key.space},
        "f8": {Key.f8}, "f9": {Key.f9}, "f10": {Key.f10},
        "capslock": {Key.caps_lock}, "insert": {getattr(Key, "insert", Key.f12)},
    }


class ChordWatcher:
    """Calls on_change(held) as a chord (e.g. ('ctrl', 'space')) goes down
    and up anywhere on the X11 desktop."""

    def __init__(self, chord, on_change):
        self._chord = tuple(chord)
        self._on_change = on_change
        self._down: set[str] = set()
        self._held = False
        self._listener = None

    def _name(self, key) -> str | None:
        for name, keys in self._map.items():
            if key in keys:
                return name
        return None

    def _update(self) -> None:
        held = all(k in self._down for k in self._chord)
        if held != self._held:
            self._held = held
            try:
                self._on_change(held)
            except Exception:
                pass

    def _press(self, key):
        n = self._name(key)
        if n:
            self._down.add(n)
            self._update()

    def _release(self, key):
        n = self._name(key)
        if n:
            self._down.discard(n)
            self._update()

    def start(self) -> bool:
        try:
            from pynput import keyboard
            self._map = _keymap()
            self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as e:
            print(f"[Keys] global key watch unavailable: {e}")
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
        self._listener = None
        if self._held:
            self._held = False
            try:
                self._on_change(False)
            except Exception:
                pass


class HotkeyPress:
    """Calls callback once each time the chord is pressed (X11, system-wide)."""

    def __init__(self, chord, callback):
        self._cb = callback
        self._watch = ChordWatcher(chord, self._edge)

    def _edge(self, held: bool) -> None:
        if held:
            try:
                self._cb()
            except Exception as e:
                print(f"[Keys] hotkey callback failed: {e}")

    def start(self) -> bool:
        return self._watch.start()

    def stop(self) -> None:
        self._watch.stop()
