import subprocess
import sys
import textwrap

from conftest import ROOT


def _run(code: str, tmp_path):
    script = textwrap.dedent(f"""
        import sys, pathlib
        sys.path.insert(0, {str(ROOT)!r})
        import core.logsetup as ls
        ls.LOG_DIR = pathlib.Path({str(tmp_path)!r})
    """) + textwrap.dedent(code)
    return subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                          text=True, timeout=60, env={**__import__("os").environ,
                                                      "QT_QPA_PLATFORM": "offscreen"})


def test_console_is_teed_to_rotating_log(tmp_path):
    out = _run("""
        ls.install()
        print("hello from the console")
        sys.stdout.flush()
    """, tmp_path)
    assert out.returncode == 0, out.stderr
    assert "hello from the console" in out.stdout
    log = (tmp_path / "jarvis.log").read_text(encoding="utf-8")
    assert "hello from the console" in log


def test_exception_in_qt_slot_does_not_kill_the_app(tmp_path):
    """Without a custom excepthook PyQt6 aborts the process here."""
    out = _run("""
        ls.install()
        seen = []
        ls.set_ui_sink(seen.append)
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer
        app = QApplication([])
        def boom():
            raise ValueError("panel bug")
        QTimer.singleShot(10, boom)
        QTimer.singleShot(200, app.quit)
        app.exec()
        print("SURVIVED", seen)
    """, tmp_path)
    assert out.returncode == 0, out.stderr[-1500:]
    assert "SURVIVED" in out.stdout and "ValueError: panel bug" in out.stdout
    crashes = list(tmp_path.glob("crash-*.txt"))
    assert crashes and "panel bug" in crashes[0].read_text(encoding="utf-8")


def test_thread_exception_is_reported(tmp_path):
    out = _run("""
        import threading
        ls.install()
        seen = []
        ls.set_ui_sink(seen.append)
        t = threading.Thread(target=lambda: 1 / 0, name="worker")
        t.start(); t.join()
        print("SEEN", seen)
    """, tmp_path)
    assert out.returncode == 0
    assert "ZeroDivisionError" in out.stdout
    assert "worker" in next(tmp_path.glob("crash-*.txt")).read_text(encoding="utf-8")
