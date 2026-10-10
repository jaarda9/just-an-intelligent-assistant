"""
Shared test setup.

Every test runs against temporary files: nothing here reads or writes the real
config/api_keys.json, the known-devices list, protocols or the owner's face,
and nothing opens the webcam or speaks.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Render Qt widgets without a visible window (and without a display on CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def fake_config(monkeypatch):
    """An in-memory api_keys.json for modules that read settings."""
    cfg: dict = {}
    import memory.config_manager as cm
    monkeypatch.setattr(cm, "load_api_keys", lambda: dict(cfg))
    return cfg


class FakePlayer:
    """Stands in for ui.JarvisUI: records what plugins show and run."""

    def __init__(self, tools=None):
        self.logs: list[str] = []
        self.panels: list[tuple[str, str]] = []
        self.gauges: list = []
        self.calls: list[tuple[str, dict]] = []
        self._tools = tools or {}

    def write_log(self, text):
        self.logs.append(text)

    def show_content(self, title, text):
        self.panels.append((title, text))

    def show_diagnostics(self, items):
        self.gauges.append(items)

    def run_tool(self, name, args):
        self.calls.append((name, dict(args)))
        fn = self._tools.get(name)
        return fn(args) if fn else f"Done: {name}"


@pytest.fixture
def player():
    return FakePlayer()
