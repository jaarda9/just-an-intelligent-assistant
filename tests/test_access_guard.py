"""Guest mode: what is blocked, what is not, and who can unlock."""
import numpy as np
import pytest


@pytest.fixture
def guard():
    from core.access import AccessGuard
    return AccessGuard()


def test_owner_mode_allows_everything(guard):
    for tool in ("send_message", "file_controller", "recall_memory", "run_protocol"):
        assert guard.check(tool, {}) is None


@pytest.mark.parametrize("tool", ["send_message", "file_controller", "file_processor",
                                  "recall_memory", "save_memory", "run_protocol", "presence",
                                  "security_report", "browser_control", "computer_control",
                                  "dev_agent", "shutdown_jarvis", "undo"])
def test_guest_blocks_owner_actions(guard, tool):
    guard.enter_guest("test")
    msg = guard.check(tool, {})
    assert msg and msg.startswith("[GUEST_MODE]")


@pytest.mark.parametrize("tool", ["web_search", "weather_report", "open_app", "youtube_video",
                                  "run_diagnostics", "system_status", "access_control"])
def test_guest_allows_general_help(guard, tool):
    guard.enter_guest("test")
    assert guard.check(tool, {}) is None


def test_computer_settings_is_split(guard):
    guard.enter_guest("test")
    assert guard.check("computer_settings", {"action": "volume_up"}) is None
    assert guard.check("computer_settings", {"action": "shutdown"})
    assert guard.check("computer_settings", {"action": "type_text", "value": "x"})
    # free-text fallback could resolve to anything → refused
    assert guard.check("computer_settings", {"description": "turn off wifi"})


def test_listeners_fire_once_per_change(guard):
    seen = []
    guard.on_change(lambda g, r: seen.append((g, r)))
    assert guard.enter_guest("a") and not guard.enter_guest("b")
    assert guard.exit_guest("c") and not guard.exit_guest("d")
    assert seen == [(True, "a"), (False, "c")]


def test_presence_drives_guest_mode(tmp_path, monkeypatch):
    import core.access as access
    import core.presence as pr
    g = access.AccessGuard()
    monkeypatch.setattr(access, "_guard", g)
    rng = np.random.default_rng(1)
    owner = rng.normal(size=128).astype(np.float32); owner /= np.linalg.norm(owner)
    other = rng.normal(size=128).astype(np.float32); other /= np.linalg.norm(other)
    np.save(tmp_path / "o.npy", owner)
    monkeypatch.setattr(pr, "_OWNER_PATH", tmp_path / "o.npy")
    monkeypatch.setattr(pr, "_config", lambda: {"presence_enabled": True})
    monkeypatch.setattr(pr, "models_ready", lambda: True)
    p = pr.Presence(); p._owner = owner; p._load = lambda: None
    scene = {"f": []}
    p._grab = lambda frames=1, **k: [np.zeros((4, 4, 3), np.uint8)]
    p._faces = lambda fr: [(e, 120.0) for e in scene["f"]]

    def look(*faces):
        scene["f"] = list(faces); p._last_look = 0; p.check()

    look(owner); look(); look()          # owner leaves
    assert not g.guest
    look(other)                          # stranger sits down
    assert g.guest
    look(owner)                          # owner returns
    assert not g.guest


def test_unlock_requires_face_not_voice(monkeypatch):
    import core.access as access
    from plugins import access_control as ac
    g = access.AccessGuard()
    monkeypatch.setattr(ac, "get_guard", lambda: g)
    g.enter_guest("test")

    class P:  # presence that sees someone else
        def verify_owner(self): return False
    monkeypatch.setattr(ac, "get_presence", lambda: P())
    assert "UNLOCK_REFUSED" in ac.run({"action": "unlock"})
    assert g.guest

    class Q:  # presence that recognises the owner
        def verify_owner(self): return True
    monkeypatch.setattr(ac, "get_presence", lambda: Q())
    ac.run({"action": "unlock"})
    assert not g.guest


def test_real_dispatcher_enforces_guest_mode(monkeypatch):
    """main.JarvisLive._execute_tool refuses before any tool branch runs."""
    import asyncio
    import types as _t
    import main
    import core.access as access
    g = access.AccessGuard()
    monkeypatch.setattr(main, "get_guard", lambda: g)
    g.enter_guest("test")

    class UI:
        muted = False
        def set_state(self, s): pass
    fake = _t.SimpleNamespace(ui=UI())
    fc = _t.SimpleNamespace(id="1", name="send_message", args={"to": "x", "text": "y"})
    resp = asyncio.run(main.JarvisLive._execute_tool(fake, fc))
    assert resp.response["result"].startswith("[GUEST_MODE]")

    # protocol steps go through _run_tool_sync — same check
    assert main.JarvisLive._run_tool_sync(fake, "file_controller", {}).startswith("[GUEST_MODE]")


def test_unlock_without_face_goes_to_screen_gate(monkeypatch):
    import core.access as access
    from plugins import access_control as ac
    g = access.AccessGuard()
    monkeypatch.setattr(ac, "get_guard", lambda: g)
    g.enter_guest("test")

    class N:
        def verify_owner(self): return None
    monkeypatch.setattr(ac, "get_presence", lambda: N())
    shown = []
    from core import confirm
    confirm.bind(lambda t, d: shown.append(t), lambda: None)
    out = ac.run({"action": "unlock"})
    assert "CONFIRMATION_PENDING" in out and shown == ["Leave guest mode"]
    assert g.guest                        # still locked until the button is pressed
    confirm.resolve(True)
    import time
    for _ in range(50):
        if not g.guest:
            break
        time.sleep(0.02)
    assert not g.guest
