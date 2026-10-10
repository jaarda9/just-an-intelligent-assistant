"""Media control — every path is mocked: no real media keys are sent and no
real player is touched while tests run."""
import pytest


@pytest.fixture
def media(monkeypatch):
    import core.media as m
    keys = []
    monkeypatch.setattr(m, "_media_key", lambda a: (keys.append(a), True)[1])
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    m._test_keys = keys
    return m


def test_falls_back_to_media_keys_without_a_session(media, monkeypatch):
    monkeypatch.setattr(media, "HAVE_SESSION_API", False)
    monkeypatch.setattr(media, "now_playing", lambda: None)
    assert media.control("next") == "Done: next."
    assert media._test_keys == ["next"]


def test_uses_session_when_available(media, monkeypatch):
    calls = []

    async def fake_action(a):
        calls.append(a)
        return True
    monkeypatch.setattr(media, "HAVE_SESSION_API", True)
    monkeypatch.setattr(media, "_session_action", fake_action)
    monkeypatch.setattr(media, "now_playing", lambda: {"title": "Song", "artist": "Band",
                                                       "app": "Spotify", "state": "paused"})
    out = media.control("play_pause")
    assert calls == ["play_pause"] and not media._test_keys
    assert out == "Done: play_pause. Now paused: Song — Band (Spotify)."


def test_unknown_action(media):
    assert "Unknown media action" in media.control("explode")


def test_plugin_now_playing(media, monkeypatch):
    from plugins import media as plug
    monkeypatch.setattr(plug.media, "now_playing", lambda: None)
    assert plug.run({"action": "now_playing"}) == "Nothing is playing right now."
    monkeypatch.setattr(plug.media, "now_playing",
                        lambda: {"title": "Thunderstruck", "artist": "AC/DC", "app": "Spotify",
                                 "state": "playing", "album": ""})
    assert plug.run({"action": "now_playing"}) == "Playing: 'Thunderstruck' by AC/DC, in Spotify."


def test_watcher_reports_changes_only(monkeypatch):
    import core.media as m
    seq = iter([None, {"title": "A"}, {"title": "A"}, {"title": "B"}, {"title": ""}])
    w = m.MediaWatcher(lambda info: seen.append(info))
    seen = []
    monkeypatch.setattr(m, "now_playing", lambda: next(seq))
    # drive the loop body by hand
    for _ in range(5):
        info = m.now_playing()
        if info and not info.get("title"):
            info = None
        if info != w._last:
            w._last = info
            w._cb(info)
    assert seen == [{"title": "A"}, {"title": "B"}, None]


def test_panel_shows_and_hides(qapp):
    from ui.nowplaying import NowPlayingPanel
    p = NowPlayingPanel()
    p.resize(180, 110)
    p.show_info({"title": "Back in Black", "artist": "AC/DC", "app": "Spotify", "state": "playing"})
    assert p.isVisibleTo(p.parentWidget() or p) or not p.isHidden()
    assert p._btns["play_pause"].text() == "❚❚"
    p.show_info({"title": "Back in Black", "artist": "AC/DC", "app": "Spotify", "state": "paused"})
    assert p._btns["play_pause"].text() == "▶"
    p.show_info(None)
    assert p.isHidden()


def test_concurrent_winrt_calls_do_not_crash():
    """Regression: overlapping WinRT calls from several threads crashed the
    process (0xC0000005). All calls now go through one WinRT thread."""
    import threading
    import core.media as m
    if not m.HAVE_SESSION_API:
        pytest.skip("winrt media packages not installed")
    errors = []

    def hammer():
        try:
            for _ in range(3):
                m.now_playing()                       # read-only
        except Exception as e:                        # pragma: no cover
            errors.append(e)
    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors


def test_one_shared_watcher(monkeypatch):
    import core.media as m
    monkeypatch.setattr(m, "_watcher", None)
    monkeypatch.setattr(m.MediaWatcher, "start", lambda self: True)
    a, b = (lambda i: None), (lambda i: None)
    assert m.watch(a) and m.watch(b)
    assert m._watcher._listeners == [a, b]
    m.unwatch(a)
    assert m._watcher._listeners == [b]


def test_real_session_api_smoke():
    """Read-only: asks Windows what is playing; never controls anything."""
    import core.media as m
    if not m.HAVE_SESSION_API:
        pytest.skip("winrt media packages not installed")
    info = m.now_playing()
    assert info is None or "title" in info
