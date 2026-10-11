"""HUD browser: URL detection, the tool, guest mode, tab management."""
import pytest


@pytest.mark.parametrize("text,url", [
    ("stark.com", "https://stark.com"),
    ("https://example.com/x", "https://example.com/x"),
    ("localhost:8000", "https://localhost:8000"),
    ("en.wikipedia.org/wiki/Iron_Man", "https://en.wikipedia.org/wiki/Iron_Man"),
    ("iron man suits", "https://www.google.com/search?q=iron+man+suits"),
    ("what is 2+2", "https://www.google.com/search?q=what+is+2%2B2"),
])
def test_to_url(text, url):
    from ui.browser import to_url
    assert to_url(text) == url


class FakeUI:
    def __init__(self):
        self.calls = []

    def browser(self, cmd, timeout=8.0, **kw):
        self.calls.append((cmd, kw))
        if cmd == "list":
            return [{"index": 0, "title": "GitHub", "url": "https://github.com", "active": False},
                    {"index": 1, "title": "Wiki", "url": "https://wiki", "active": True}]
        if cmd == "read":
            return ("Wiki", "https://wiki", "Tony   Stark\n\nis Iron Man " + "x" * 7000)
        return f"ok:{cmd}"


def test_tool_actions():
    from plugins import hud_browser as hb
    ui = FakeUI()
    assert hb.run({"action": "open", "target": "github.com"}, player=ui) == "ok:open"
    assert ui.calls[-1] == ("open", {"target": "github.com", "new_tab": True})
    hb.run({"action": "open", "target": "x", "new_tab": False}, player=ui)
    assert ui.calls[-1][1]["new_tab"] is False
    assert hb.run({"action": "list"}, player=ui) == "Open tabs: 1. GitHub; 2. Wiki (showing)."
    hb.run({"action": "switch", "index": 2}, player=ui)
    assert ui.calls[-1] == ("switch", {"index": 1})               # 1-based → 0-based
    out = hb.run({"action": "read"}, player=ui)
    assert out.startswith("Page: Wiki — https://wiki") and "Tony Stark is Iron Man" in out
    assert "(truncated)" in out
    assert "Tell me what to open" in hb.run({"action": "open"}, player=ui)


def test_browser_blocked_in_guest_mode():
    from core.access import AccessGuard
    g = AccessGuard()
    g.enter_guest("t")
    assert g.check("hud_browser", {"action": "open", "target": "mail.google.com"})


def test_websites_route_to_hud_browser():
    from actions.open_app import TOOL as open_app
    from actions.browser_control import TOOL as bc
    assert "hud_browser" in open_app["description"]
    assert "hud_browser" in bc["description"]


def test_tab_management(qapp):
    from ui.browser import HAVE_WEBENGINE, HudBrowser
    if not HAVE_WEBENGINE:
        pytest.skip("PyQt6-WebEngine not installed")
    b = HudBrowser()
    closed = []
    b.closed.connect(lambda: closed.append(1))
    b.open("about:blank")
    b.open("about:blank")
    b.open("about:blank", new_tab=False)
    assert len(b.tabs()) == 2 and b.tabs()[1]["active"]
    assert b.switch(0) and b.tabs()[0]["active"] and not b.switch(9)
    b.close_tab(0)
    assert len(b.tabs()) == 1 and not closed
    b.close_tab()
    assert not b.has_tabs() and closed == [1]               # last tab → back to the HUD
    b.open("about:blank")
    b.shutdown()                                            # pages before profile
    assert not b.has_tabs() and b._profile is None


def test_centre_returns_to_browser_after_video(qapp, monkeypatch):
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)
    from ui.browser import HAVE_WEBENGINE
    if not HAVE_WEBENGINE:
        pytest.skip("PyQt6-WebEngine not installed")
    from ui.window import MainWindow
    w = MainWindow("face.png")
    try:
        w._on_browser_cmd("open", {"target": "about:blank"})
        assert w._hud_cam_stack.currentIndex() == 3
        w._hud_cam_stack.setCurrentIndex(2)          # a video takes the centre…
        w._restore_centre()                          # …and leaves
        assert w._hud_cam_stack.currentIndex() == 3
        w._on_browser_cmd("hide", {})
        assert w._hud_cam_stack.currentIndex() == 0
    finally:
        w._browser.shutdown()
        w.hud._tmr.stop(); w._chip_timer.stop(); w.deleteLater()
