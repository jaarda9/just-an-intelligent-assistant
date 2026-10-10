"""
Task board — what JARVIS is busy with right now.

Every tool call is registered at the dispatcher (main.py), so nothing has to
opt in; long-running work can also report progress (protocols report each
step). The HUD's TASKS panel subscribes and only shows a task once it has
been running for a moment, so instant actions never flicker on screen.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# Friendlier names for the panel; anything else shows its tool name.
LABELS = {
    "web_search": "Searching the web", "browser_control": "Browsing",
    "dev_agent": "Writing code", "code_helper": "Working on code",
    "file_processor": "Reading a file", "file_controller": "Managing files",
    "run_protocol": "Protocol", "run_diagnostics": "Diagnostics",
    "youtube_video": "Finding a video", "video_player": "Opening a video",
    "flight_finder": "Searching flights", "game_updater": "Updating games",
    "send_message": "Sending a message", "screen_process": "Looking",
    "weather_report": "Weather", "presence": "Presence", "security_report": "Security sweep",
    "reminder": "Setting a reminder", "open_app": "Opening an app",
}


@dataclass
class Task:
    id: int
    name: str
    detail: str = ""
    progress: Optional[float] = None      # 0..1, or None = indeterminate
    started: float = field(default_factory=time.monotonic)
    finished: Optional[float] = None
    ok: Optional[bool] = None

    @property
    def elapsed(self) -> float:
        return (self.finished or time.monotonic()) - self.started


class TaskBoard:
    LINGER_S = 6.0          # finished tasks stay visible this long

    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._tasks: dict[int, Task] = {}
        self._listeners: list[Callable[[], None]] = []
        self._local = threading.local()

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _changed(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    def start(self, tool: str, detail: str = "") -> int:
        with self._lock:
            tid = next(self._ids)
            self._tasks[tid] = Task(tid, LABELS.get(tool, tool.replace("_", " ").title()), detail)
        self._local.current = tid
        self._changed()
        return tid

    def update(self, tid: Optional[int] = None, progress: Optional[float] = None,
               detail: Optional[str] = None, name: Optional[str] = None) -> None:
        """Report progress. Without an id: the calling thread's task, or the
        newest running task with this display name (tools run on executor
        threads, so a protocol step cannot always see its own task id)."""
        tid = tid if tid is not None else getattr(self._local, "current", None)
        with self._lock:
            if tid is None and name:
                running = [t for t in self._tasks.values() if not t.finished and t.name == name]
                tid = max(running, key=lambda t: t.started).id if running else None
            t = self._tasks.get(tid) if tid is not None else None
            if t is None or t.finished:
                return
            if progress is not None:
                t.progress = max(0.0, min(1.0, progress))
            if detail is not None:
                t.detail = detail
        self._changed()

    def finish(self, tid: int, ok: bool = True, detail: Optional[str] = None) -> None:
        with self._lock:
            t = self._tasks.get(tid)
            if t is None:
                return
            t.finished, t.ok = time.monotonic(), ok
            if detail is not None:
                t.detail = detail
            if ok and t.progress is not None:
                t.progress = 1.0
        if getattr(self._local, "current", None) == tid:
            self._local.current = None
        self._changed()

    def snapshot(self, min_age: float = 0.8) -> list[Task]:
        """Tasks worth showing: running ≥ min_age, or finished within LINGER_S."""
        now = time.monotonic()
        with self._lock:
            for tid in [k for k, t in self._tasks.items()
                        if t.finished and now - t.finished > self.LINGER_S]:
                del self._tasks[tid]
            out = [t for t in self._tasks.values()
                   if (t.finished and (t.finished - t.started) >= min_age) or
                   (not t.finished and now - t.started >= min_age)]
        return sorted(out, key=lambda t: (t.finished is not None, -t.started))[:5]

    def active(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if not t.finished)


_board: TaskBoard | None = None
_blk = threading.Lock()


def get_board() -> TaskBoard:
    global _board
    with _blk:
        if _board is None:
            _board = TaskBoard()
        return _board
