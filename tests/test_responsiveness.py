"""Response speed presets, the duplicate-call guard, and parallel tool calls."""
import asyncio
import time
import types as _t

import pytest


@pytest.fixture
def cfg(monkeypatch):
    import memory.config_manager as cm
    data = {}
    monkeypatch.setattr(cm, "load_api_keys", lambda: dict(data))
    return cm, data


def test_default_is_fast(cfg):
    cm, data = cfg
    assert cm.get_response_speed() == "fast"
    assert cm.get_proactive_audio_enabled() is False
    t = cm.get_turn_tuning()
    assert t["enabled"] and t["silence_ms"] == 550 and t["end_sensitivity"] == "high"


def test_presets(cfg):
    cm, data = cfg
    data["response_speed"] = "balanced"
    assert cm.get_proactive_audio_enabled() is True and not cm.get_turn_tuning()["enabled"]
    data["response_speed"] = "fastest"
    assert cm.get_turn_tuning()["silence_ms"] == 350
    data["response_speed"] = "warp"
    assert cm.get_response_speed() == "fast"


def test_explicit_keys_win(cfg):
    cm, data = cfg
    data.update(response_speed="fast", proactive_audio=True,
                turn_tuning={"enabled": False, "silence_ms": 900})
    assert cm.get_proactive_audio_enabled() is True
    t = cm.get_turn_tuning()
    assert not t["enabled"] and t["silence_ms"] == 900


def _live():
    import main
    ns = _t.SimpleNamespace(_recent_calls={})
    ns._call_key = main.JarvisLive._call_key            # staticmethod: no binding
    for name in ("_duplicate_of", "_remember_call"):
        setattr(ns, name, getattr(main.JarvisLive, name).__get__(ns))
    return main, ns


def test_duplicate_guard():
    main, ns = _live()
    args = {"action": "open", "target": "https://github.com"}
    assert ns._duplicate_of("hud_browser", args) is None
    ns._remember_call("hud_browser", args, "Opened in tab 1.")
    assert ns._duplicate_of("hud_browser", dict(args)) == "Opened in tab 1."
    assert ns._duplicate_of("hud_browser", {**args, "target": "x"}) is None


def test_repeatable_actions_are_not_blocked():
    main, ns = _live()
    ns._remember_call("computer_settings", {"action": "volume_up"}, "Done")
    assert ns._duplicate_of("computer_settings", {"action": "volume_up"}) is None
    ns._remember_call("media_control", {"action": "next"}, "Done")
    assert ns._duplicate_of("media_control", {"action": "next"}) is None
    ns._remember_call("media_control", {"action": "play"}, "Done")      # resume is not
    assert ns._duplicate_of("media_control", {"action": "play"}) == "Done"


def test_guard_expires():
    main, ns = _live()
    ns._remember_call("open_app", {"app_name": "x"}, "ok")
    k = ns._call_key("open_app", {"app_name": "x"})
    ns._recent_calls[k] = (time.monotonic() - main.DUP_WINDOW_S - 1, "ok")
    assert ns._duplicate_of("open_app", {"app_name": "x"}) is None


def test_page_reread_is_refused(monkeypatch):
    from plugins import hud_browser as hb
    monkeypatch.setattr(hb, "_last_read", {"url": "", "at": 0.0})

    class UI:
        def browser(self, cmd, timeout=8.0, **kw):
            return ("Wiki", "https://wiki", "text " * 2000)
    first = hb.run({"action": "read"}, player=UI())
    assert first.startswith("Page: Wiki") and len(first) < 3400
    assert hb.run({"action": "read"}, player=UI()).startswith("[ALREADY_READ]")


def test_play_named_thing_routes_to_video_player():
    from plugins.media import PLUGIN
    assert "video_player" in PLUGIN["description"] and "RESUME" in PLUGIN["description"]
