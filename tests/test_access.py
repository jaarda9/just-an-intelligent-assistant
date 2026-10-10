"""Mark IV access points: tray, summon, close behaviour."""
import platform

import pytest


@pytest.fixture
def win(qapp, monkeypatch):
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.window import MainWindow
    w = MainWindow("face.png")
    yield w
    w.hud._tmr.stop()
    w._chip_timer.stop()
    try:
        w._summon_key.stop()
    except Exception:
        pass
    if w._tray:
        w._tray.hide()
    w.deleteLater()


@pytest.mark.skipif(platform.system() != "Windows", reason="RegisterHotKey is Windows-only")
def test_global_hotkey_registers_and_releases():
    from core.summon import GlobalHotkey, MOD_ALT, MOD_CONTROL, MOD_SHIFT
    chord = (MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x7B)         # Ctrl+Alt+Shift+F12
    hk = GlobalHotkey(lambda: None, chord=chord, label="test")
    assert hk.start() in ("global", "unavailable")
    if hk.scope == "global":
        # a second registration of the same chord must fail while held…
        hk2 = GlobalHotkey(lambda: None, chord=chord, label="test")
        assert hk2.start() == "unavailable"
        hk.stop()
        # …and succeed once released
        hk3 = GlobalHotkey(lambda: None, chord=chord, label="test")
        assert hk3.start() == "global"
        hk3.stop()


def test_summon_cycles_through_states(win, qapp):
    win.show()
    win.enter_mini()
    assert win._mini.isVisible()
    win.summon()                                   # from mini → full HUD
    assert win.isVisible() and not win._mini.isVisible()
    win.hide()
    win.summon()                                   # from hidden → shown
    assert win.isVisible()


def test_tray_icon_follows_state(win):
    if win._tray is None:
        pytest.skip("no system tray in this environment")
    win._apply_state("THINKING")
    k1 = win._tray._last_key
    win._apply_state("LISTENING")
    assert win._tray._last_key != k1
    assert "listening" in win._tray.toolTip()
    win._set_muted(True)
    assert "muted" in win._tray.toolTip()


def test_tray_protocol_menu_lists_protocols(win, tmp_path, monkeypatch):
    if win._tray is None:
        pytest.skip("no system tray in this environment")
    from plugins import protocols
    monkeypatch.setattr(protocols, "PROTOCOLS_PATH", tmp_path / "p.json")
    win._tray._fill_protocols()
    names = [a.text() for a in win._tray._protocols.actions()]
    assert {"Work", "Night", "Status"} <= set(names)


def test_tray_protocol_runs_through_dispatcher(win, tmp_path, monkeypatch):
    if win._tray is None:
        pytest.skip("no system tray in this environment")
    import threading
    called = threading.Event()
    seen = []
    win.run_tool = lambda name, args: (seen.append((name, args)), called.set())
    win._tray._run_protocol("night")
    assert called.wait(2)
    assert seen == [("run_protocol", {"name": "night"})]
