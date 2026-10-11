"""System settings overlay — writes go to a temporary config file."""
import json

import pytest


@pytest.fixture
def ov(qapp, tmp_path, monkeypatch):
    import memory.config_manager as cm
    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "api_keys.json")
    monkeypatch.setattr(cm, "ensure_config_dir", lambda: None)
    import core.access as access
    monkeypatch.setattr(access, "_guard", access.AccessGuard())
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.window import MainWindow
    from ui.settings_overlay import SettingsOverlay
    win = MainWindow("face.png")
    o = SettingsOverlay(win)
    yield o, win, tmp_path / "api_keys.json"
    win.hud._tmr.stop(); win._chip_timer.stop(); o.deleteLater(); win.deleteLater()


def _cfg(path):
    return json.loads(path.read_text()) if path.exists() else {}


def test_interface_switches_persist(ov):
    o, win, path = ov
    boxes = {cb.text(): cb for cb in o.findChildren(type(o._presence_cb))}
    sfx = next(cb for t, cb in boxes.items() if t.startswith("Sound effects"))
    sfx.setChecked(False)
    assert _cfg(path)["sfx_enabled"] is False
    tray = next(cb for t, cb in boxes.items() if t.startswith("Close to the tray"))
    tray.setChecked(True)
    assert _cfg(path)["close_to_tray"] is True


def test_hud_style_applies_live(ov):
    o, win, path = ov
    o._style.setCurrentIndex(o._style.findData("ring"))
    assert win.hud.hud_style == "ring" and _cfg(path)["hud_style"] == "ring"


def test_lock_down_from_settings(ov):
    o, win, path = ov
    from core.access import get_guard
    o._lock()
    assert get_guard().guest
    assert "Guest mode is ON" in o._labels["guest"].text()


def test_presence_switch_disabled_until_enrolled(ov, monkeypatch):
    o, win, path = ov
    from core.presence import get_presence
    assert o._presence_cb.isEnabled() == get_presence().enrolled()


def test_google_tab_reflects_setup_state(ov, monkeypatch):
    o, win, path = ov
    import core.google_services as g
    monkeypatch.setattr(g, "status", lambda: "needs_client")
    o._refresh_google()
    assert "client_secret.json" in o._labels["google"].text()
    assert not o._g_connect.isEnabled() and not o._g_disconnect.isEnabled()
    monkeypatch.setattr(g, "status", lambda: "ready")
    o._refresh_google()
    assert o._g_disconnect.isEnabled() and "cannot send" in o._labels["google"].text()


def test_renders(ov):
    o, win, path = ov
    for i in range(o._tabs.count()):
        o._tabs.setCurrentIndex(i)
        assert not o.grab().isNull()
