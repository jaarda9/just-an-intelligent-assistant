"""
Global summon hotkey — bring JARVIS to the front from any application.

Windows: RegisterHotKey on a small thread with its own message loop. Unlike
push-to-talk (core/hotkey.py), summoning only needs the *press*, so the OS
can do the work: no polling, zero CPU while idle, and the chord is reserved
system-wide while JARVIS runs. If another program already owns the chord,
registration fails and `scope` says so.

Linux on X11 with `pynput` installed: a system-wide key watch (see
core/linux_keys.py). Elsewhere (Wayland, macOS, no pynput) there is no global
hook without accessibility permissions, so the window binds the same chord as
an application shortcut (scope "window").
"""
from __future__ import annotations

import platform
import threading
from typing import Callable

_OS = platform.system()

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

DEFAULT_LABEL = "Ctrl+Alt+J"
_DEFAULT = (MOD_CONTROL | MOD_ALT, ord("J"))


class GlobalHotkey:
    def __init__(self, on_press: Callable[[], None], chord=_DEFAULT, label: str = DEFAULT_LABEL):
        self._cb = on_press
        self._mods, self._vk = chord
        self.label = label
        self.scope = "window"
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._linux = None

    def start(self) -> str:
        if _OS == "Linux":
            from core import linux_keys
            if self._linux is None and linux_keys.global_keys_available():
                hk = linux_keys.HotkeyPress(("ctrl", "alt", "j"), self._cb)
                if hk.start():
                    self._linux, self.scope = hk, "global"
            return self.scope
        if _OS != "Windows":
            return self.scope
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="summon-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self.scope

    def stop(self) -> None:
        if self._linux is not None:
            self._linux.stop()
            self._linux = None
            self.scope = "window"
        if self._tid:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread, self._tid, self.scope = None, 0, "window"

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._tid = kernel32.GetCurrentThreadId()
        hk_id = 0xA11E
        if not user32.RegisterHotKey(None, hk_id, self._mods | MOD_NOREPEAT, self._vk):
            self.scope = "unavailable"          # another program owns the chord
            self._ready.set()
            return
        self.scope = "global"
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == hk_id:
                    try:
                        self._cb()
                    except Exception as e:
                        print(f"[Summon] callback failed: {e}")
        finally:
            user32.UnregisterHotKey(None, hk_id)
