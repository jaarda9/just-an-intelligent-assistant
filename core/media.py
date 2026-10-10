"""
Media control and Now Playing — for whatever player the OS considers current
(Spotify, a browser tab, VLC, the Media Player app…).

Windows: the system media session API (GlobalSystemMediaTransportControls,
via the optional winrt packages) gives the title/artist and precise
play/pause/skip for the current session. Without those packages — or with no
session — it falls back to the media keys, which every player honours.
Linux: playerctl if installed. macOS: not supported (reported honestly).
"""
from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

_OS = platform.system()
ACTIONS = ("play_pause", "play", "pause", "next", "previous", "stop")
_VK = {"play_pause": 0xB3, "play": 0xB3, "pause": 0xB3, "next": 0xB0,
       "previous": 0xB1, "stop": 0xB2}

try:
    from winrt.windows.media.control import (  # type: ignore
        GlobalSystemMediaTransportControlsSessionManager as _Manager,
    )
    HAVE_SESSION_API = True
except Exception:
    _Manager = None
    HAVE_SESSION_API = False


# Every WinRT call runs on ONE dedicated thread. Concurrent calls from
# several threads (the watcher plus a voice command, say) crashed the process
# with an access violation in testing; a single-worker executor makes overlap
# impossible and keeps WinRT on one apartment.
from concurrent.futures import ThreadPoolExecutor as _TPE
_WINRT = _TPE(max_workers=1, thread_name_prefix="winrt")


def _run(coro_fn, *args, timeout: float = 5.0):
    """Run a WinRT coroutine function on the WinRT thread and wait for it."""
    return _WINRT.submit(lambda: asyncio.run(coro_fn(*args))).result(timeout=timeout)


async def _session():
    mgr = await _Manager.request_async()
    return mgr.get_current_session()


async def _now_playing_async() -> Optional[dict]:
    s = await _session()
    if s is None:
        return None
    props = await s.try_get_media_properties_async()
    status = s.get_playback_info().playback_status
    # PlaybackStatus enum: 4 = playing, 5 = paused (others: closed/opened/changing/stopped)
    state = {4: "playing", 5: "paused"}.get(int(status), "stopped")
    app = (s.source_app_user_model_id or "").split("!")[0].split("\\")[-1]
    app = app.removesuffix(".exe")
    return {"title": props.title or "", "artist": props.artist or "",
            "album": props.album_title or "", "app": app, "state": state}


def now_playing() -> Optional[dict]:
    """{'title','artist','album','app','state'} or None (nothing / unsupported)."""
    if HAVE_SESSION_API:
        try:
            return _run(_now_playing_async)
        except Exception:
            return None
    if _OS == "Linux" and shutil.which("playerctl"):
        try:
            out = subprocess.run(["playerctl", "metadata", "--format",
                                  "{{status}}\t{{title}}\t{{artist}}\t{{playerName}}"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            if out:
                st, title, artist, app = (out.split("\t") + ["", "", "", ""])[:4]
                return {"title": title, "artist": artist, "album": "", "app": app,
                        "state": st.lower() if st else "stopped"}
        except Exception:
            pass
    return None


async def _session_action(action: str) -> bool:
    s = await _session()
    if s is None:
        return False
    fn = {"play_pause": s.try_toggle_play_pause_async, "play": s.try_play_async,
          "pause": s.try_pause_async, "next": s.try_skip_next_async,
          "previous": s.try_skip_previous_async, "stop": s.try_stop_async}[action]
    return bool(await fn())


def _media_key(action: str) -> bool:
    if _OS == "Windows":
        import ctypes
        vk = _VK[action]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)        # KEYEVENTF_KEYUP
        return True
    if _OS == "Linux" and shutil.which("playerctl"):
        cmd = {"play_pause": "play-pause", "previous": "previous"}.get(action, action)
        return subprocess.run(["playerctl", cmd], capture_output=True, timeout=3).returncode == 0
    return False


def control(action: str) -> str:
    """Do it; return a short sentence about what happened."""
    action = (action or "").lower().strip()
    if action not in ACTIONS:
        return f"Unknown media action '{action}'."
    done = False
    if HAVE_SESSION_API:
        try:
            done = _run(_session_action, action)
        except Exception:
            done = False
    if not done:
        done = _media_key(action)
    if not done:
        return "Media control is not available on this system."
    time.sleep(0.4)                       # let the player update before reporting
    np = now_playing()
    if np and np["title"]:
        return f"Done: {action}. Now {np['state']}: {np['title']}" + \
               (f" — {np['artist']}" if np["artist"] else "") + f" ({np['app']})."
    return f"Done: {action}."


class MediaWatcher:
    """Polls Now Playing every few seconds on its own thread and calls each
    listener with info_or_None only when something changes. Use watch() /
    unwatch() — one shared watcher per process, however many windows."""

    def __init__(self, on_change: Callable[[Optional[dict]], None] | None = None,
                 period: float = 3.0):
        self._listeners: list = [on_change] if on_change else []
        self._period = period
        self._last: Optional[dict] = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _cb(self, info) -> None:
        for fn in list(self._listeners):
            try:
                fn(info)
            except Exception as e:          # e.g. a window that has been deleted
                print(f"[Media] listener failed: {e}")

    def start(self) -> bool:
        if not (HAVE_SESSION_API or (_OS == "Linux" and shutil.which("playerctl"))):
            return False
        self._thread = threading.Thread(target=self._loop, name="media-watch", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            info = now_playing()
            if info and not info.get("title"):
                info = None
            if info != self._last:
                self._last = info
                self._cb(info)
            self._stop.wait(self._period)


_watcher: MediaWatcher | None = None
_wlock = threading.Lock()


def watch(fn: Callable[[Optional[dict]], None]) -> bool:
    """Subscribe to Now Playing changes (starts the shared watcher once).
    Returns False when Now Playing is unsupported here."""
    global _watcher
    with _wlock:
        if _watcher is None:
            _watcher = MediaWatcher()
            if not _watcher.start():
                _watcher = None
                return False
        _watcher._listeners.append(fn)
        last = _watcher._last
    if last is not None:
        fn(last)                             # a late subscriber gets the current track
    return True


def unwatch(fn) -> None:
    with _wlock:
        if _watcher is not None and fn in _watcher._listeners:
            _watcher._listeners.remove(fn)
