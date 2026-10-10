import pytest
from PyQt6.QtCore import Qt


@pytest.fixture
def win(qapp, monkeypatch):
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.window import MainWindow
    w = MainWindow("face.png")
    w.resize(1200, 760)
    yield w
    w.hud._tmr.stop()
    w._chip_timer.stop()
    w.close()
    w.deleteLater()


def test_glass_panel_and_chip_render(qapp):
    from ui.chrome import GlassPanel, IconButton, StatusChip, WindowButton
    for widget in (GlassPanel("Systems"), StatusChip("Voice link"),
                   IconButton("gear"), IconButton("sliders"), WindowButton("close")):
        widget.resize(160, 60)
        img = widget.grab().toImage()
        assert not img.isNull()


def test_status_chips_reflect_state(win):
    win.hud.state = "THINKING"
    win._refresh_status_chips()
    assert win._chip_voice._level == "ok" and win._chip_voice._value == "thinking"
    win.hud.state = "SLEEPING"
    win._refresh_status_chips()
    assert win._chip_voice._value == "standby"
    win._muted = True
    win._refresh_status_chips()
    assert win._chip_voice._value == "mic muted"
    assert win._chip_presence._value in ("not set up", "off", "at the desk", "away", "watching")


def test_frameless_by_default(win):
    assert win._frameless
    assert win.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_frameless_can_be_turned_off(qapp, monkeypatch):
    import ui.hud
    import ui.window as uw
    monkeypatch.setattr(ui.hud, "_sfx", None)
    monkeypatch.setattr(uw, "_read_full_config", lambda: {"frameless": False})
    w = uw.MainWindow("face.png")
    assert not w._frameless
    assert not (w.windowFlags() & Qt.WindowType.FramelessWindowHint)
    w.hud._tmr.stop(); w._chip_timer.stop(); w.close(); w.deleteLater()


def test_fonts_registered(win):
    from PyQt6.QtGui import QFontDatabase
    fams = set(QFontDatabase.families())
    assert {"Rajdhani", "Orbitron", "Share Tech Mono"} <= fams
