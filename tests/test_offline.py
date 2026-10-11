"""Offline mode: local commands and honest status."""
import pytest


@pytest.mark.parametrize("text,expected", [
    ("run work protocol", ("run_protocol", {"name": "work"})),
    ("Jarvis, initiate the house party protocol", ("run_protocol", {"name": "house party"})),
    ("good night protocol", ("run_protocol", {"name": "good night"})),
    ("run diagnostics", ("run_diagnostics", {})),
    ("system check please", ("run_diagnostics", {})),
    ("pause the music", ("media_control", {"action": "play_pause"})),
    ("next track", ("media_control", {"action": "next"})),
    ("skip", ("media_control", {"action": "next"})),
    ("what's playing?", ("media_control", {"action": "now_playing"})),
    ("volume 30", ("computer_settings", {"action": "volume_set", "value": "30"})),
    ("set volume to 250%", ("computer_settings", {"action": "volume_set", "value": "100"})),
    ("volume up", ("computer_settings", {"action": "volume_up"})),
    ("mute", ("computer_settings", {"action": "mute"})),
    ("lock the screen", ("computer_settings", {"action": "lock_screen"})),
    ("lock down", ("access_control", {"action": "lock"})),
    ("open Spotify", ("open_app", {"app_name": "spotify"})),
    ("can you open visual studio code", ("open_app", {"app_name": "visual studio code"})),
])
def test_routes(text, expected):
    from core.local_commands import route
    assert route(text) == expected


@pytest.mark.parametrize("text", ["what's the weather in Paris", "write me a poem",
                                  "who won the game last night", "", "   "])
def test_needs_the_model(text):
    from core.local_commands import route
    assert route(text) is None


def test_handle_strips_model_instructions():
    from core.local_commands import handle
    out = handle("run work protocol",
                 lambda t, a: "[PROTOCOL work] 3/3 steps succeeded. Tell the user, in one short sentence…")
    assert out == "[PROTOCOL work] 3/3 steps succeeded."
    diag = ("SYSTEMS DIAGNOSTIC\n\nCPU 5%\n\nAll systems nominal.\n\n"
            "The full readout is already on the HUD. Give the user a two-sentence status report")
    assert handle("diagnostics", lambda t, a: diag) == "All systems nominal."


def test_offline_text_runs_locally_and_guest_mode_still_applies(monkeypatch):
    import types as _t
    import main
    import core.access as access
    g = access.AccessGuard()
    monkeypatch.setattr(main, "get_guard", lambda: g)
    logs, ran = [], []
    fake = _t.SimpleNamespace(
        ui=_t.SimpleNamespace(write_log=logs.append), _asst_name="JARVIS",
        _run_tool_sync=lambda n, a: (ran.append((n, a)), "Done: mute.")[1])
    reply = main.JarvisLive._run_local_command(fake, "mute")
    assert reply == "Done: mute." and logs == ["JARVIS: Done: mute."]
    assert main.JarvisLive._run_local_command(fake, "write a sonnet").startswith("I'm offline")
    assert main.JarvisLive._run_local_command(fake, "[FILE_UPLOADED] x") == ""
    # the real dispatcher still refuses restricted tools offline
    g.enter_guest("t")
    fake2 = _t.SimpleNamespace(ui=fake.ui, _asst_name="JARVIS",
                               _action_registry=None, _plugin_registry=None)
    fake2._run_tool_sync = lambda n, a: main.JarvisLive._run_tool_sync(fake2, n, a)
    assert main.JarvisLive._run_local_command(fake2, "run work protocol").startswith("[GUEST_MODE]")


def test_hud_and_chip_show_offline(qapp, monkeypatch):
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.window import MainWindow
    w = MainWindow("face.png")
    try:
        w._apply_state("OFFLINE")
        w._refresh_status_chips()
        assert w._chip_voice._level == "alert" and "offline" in w._chip_voice._value
        main_c, acc = w.hud._state_colours()
        assert acc.name() != "#00ff88"
        w.hud.grab()
        w._apply_state("RECONNECTING")
        w._refresh_status_chips()
        assert w._chip_voice._value == "reconnecting"
    finally:
        w.hud._tmr.stop(); w._chip_timer.stop(); w.deleteLater()


def test_back_online_chirps(monkeypatch):
    from core import sfx
    played = []
    monkeypatch.setattr(sfx, "play", played.append)
    sfx.on_state_change("OFFLINE", "LISTENING")
    assert played == ["wake"]
