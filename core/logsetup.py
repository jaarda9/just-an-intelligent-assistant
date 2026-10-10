"""
Local log file and crash reports.

  logs/jarvis.log            everything printed to the console, rotated at
                             1 MB, three old files kept (logs/ is git-ignored).
  logs/crash-<time>.txt      one file per unhandled exception, with the full
                             traceback.

The exception hooks matter beyond record-keeping: PyQt6 aborts the whole
process when an exception escapes a Qt slot *unless* sys.excepthook has been
replaced. With these installed, a bug in one panel costs that action, not the
assistant.

Everything stays on this machine. The log can contain what was said to the
assistant and tool arguments, because the console does.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

_logger: logging.Logger | None = None
_ui_sink = None            # callable(str) → activity log, set once the UI exists
_installed = False


class _Tee:
    """Writes to the original stream and, line by line, to the log file."""

    def __init__(self, stream, level: int):
        self._stream = stream
        self._level = level
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, text):
        try:
            if self._stream is not None:
                self._stream.write(text)
        except Exception:
            pass
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip() and _logger is not None:
                    _logger.log(self._level, line)
        return len(text)

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):              # isatty, encoding, reconfigure…
        return getattr(self._stream, name)


def _write_crash(kind: str, exc_type, exc, tb) -> Path | None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / time.strftime(f"crash-%Y%m%d-%H%M%S.txt")
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path.write_text(f"{kind} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}",
                        encoding="utf-8")
        return path
    except Exception:
        return None


def _report(kind: str, exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    path = _write_crash(kind, exc_type, exc, tb)
    try:
        traceback.print_exception(exc_type, exc, tb)
    except Exception:
        pass
    if _ui_sink is not None:
        try:
            where = f" — details in logs/{path.name}" if path else ""
            _ui_sink(f"ERR: {exc_type.__name__}: {str(exc)[:120]}{where}")
        except Exception:
            pass


def _excepthook(exc_type, exc, tb):
    _report("Unhandled exception", exc_type, exc, tb)


def _thread_hook(args: threading.ExceptHookArgs):
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, "name", "?")
    _report(f"Unhandled exception in thread '{name}'", args.exc_type, args.exc_value,
            args.exc_traceback)


def install() -> None:
    """Idempotent. Call once, as early as possible in main()."""
    global _logger, _installed
    if _installed:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_DIR / "jarvis.log", maxBytes=1_000_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s %(message)s",
                                               "%Y-%m-%d %H:%M:%S"))
        _logger = logging.getLogger("jarvis.console")
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        _logger.addHandler(handler)
        sys.stdout = _Tee(sys.stdout, logging.INFO)
        sys.stderr = _Tee(sys.stderr, logging.WARNING)
    except Exception as e:                    # a read-only folder must not stop the app
        print(f"[Log] file logging unavailable: {e}")
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    _installed = True
    print(f"[Log] session start — {time.strftime('%Y-%m-%d %H:%M:%S')}")


def set_ui_sink(fn) -> None:
    """Route crash notices to the activity log once the UI is up."""
    global _ui_sink
    _ui_sink = fn
