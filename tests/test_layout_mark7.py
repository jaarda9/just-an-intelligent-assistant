"""Mark VII layout pass: COMMS transcript, SYSTEMS graphs, presence overlay,
attach/drop, footer hint, browser address bar and dark pages."""
import pytest


@pytest.fixture
def log(qapp):
    from ui.widgets import LogWidget
    w = LogWidget()
    w.resize(320, 500)
    return w


def _drain(qapp):
    qapp.processEvents()


def test_transcript_classifies_lines(log):
    c = log._classify
    assert c("You: hello") == ("you", "hello", "")
    assert c("YOU (terminal): status") == ("you", "status", "terminal")
    assert c("YOU: (tray) Focus protocol") == ("you", "Focus protocol", "tray")
    assert c("[Web]: lights on") == ("you", "lights on", "phone")
    assert c("JARVIS: At once, sir.") == ("ai", "At once, sir.", "")
    assert c("[open_app] Spotify") == ("tool", "Spotify", "open_app")
    assert c("ERR: web_search — quota")[0] == "err"
    assert c("SYS: JARVIS online.") == ("sys", "JARVIS online.", "")


def test_tools_attach_to_the_next_reply(log, qapp):
    for line in ("[open_app] Spotify", "[Search:web] mark vii", "You: open spotify",
                 "JARVIS: Done, sir."):
        log.append_log(line)
    _drain(qapp)
    kinds = [getattr(getattr(e, "card", None), "kind", None) for e in log.entries()]
    assert kinds == ["you", "ai"]
    ai = log.entries()[-1].card
    assert ai.tools.text() == "⚙ USED  open app  ·  search"
    log._finish_typing()
    assert ai.body.text() == "Done, sir."
    assert log._pending_tools == []


def test_unclaimed_tools_show_on_their_own(log, qapp):
    log.append_log("[file] read notes.txt")
    _drain(qapp)
    assert log.entries() == []
    log._flush_tools()
    assert log.entries()[-1].kind == "tool"


def test_empty_state_and_cap(log, qapp):
    assert not log._empty.isHidden()
    log.MAX_ENTRIES = 5
    for i in range(9):
        log.append_log(f"SYS: line {i}")
    _drain(qapp)
    assert log._empty.isHidden()
    assert len(log.entries()) == 5
    assert log.entries()[-1].text().endswith("line 8")


def test_metric_bar_history_and_colours(qapp):
    from ui.base import C
    from ui.widgets import MetricBar
    b = MetricBar("CPU")
    for v in (10, 20, 75, 95):
        b.set_value(v, f"{v}%")
    assert list(b._hist) == [10, 20, 75, 95]
    assert b._level_colour().name() == C.RED.lower()
    b.set_value(72, "72%")
    assert b._level_colour().name() == C.WARN.lower()
    b.set_value(10, "10%")
    assert b._level_colour().name() == C.PRI.lower()
    b.resize(170, 34)
    b.grab()


def test_short_url():
    from ui.browser import short_url
    assert short_url("https://www.github.com/a/b?x=1") == "github.com/a/b"
    assert short_url("https://en.wikipedia.org/wiki/Iron_Man%27s_armor") == \
        "en.wikipedia.org/wiki/Iron_Man's_armor"
    long = "https://example.com/" + "x" * 80
    assert short_url(long) == "example.com"
    assert short_url("file:///C:/tmp/My%20page.html") == "My page.html"
    assert short_url("about:blank") == "about:blank"


@pytest.fixture
def win(qapp):
    import ui.hud
    ui.hud._sfx = None
    from ui.window import MainWindow
    w = MainWindow("face.png")
    if getattr(w, "_overlay", None):
        w._overlay.hide()
    w.resize(1280, 800)
    yield w
    w._browser.shutdown()
    w.deleteLater()


def test_presence_overlay_only_off_the_hud(win):
    ov = win._presence
    assert ov.isHidden()                      # page 0 = the HUD itself
    win._hud_cam_stack.setCurrentIndex(2)
    assert not ov.isHidden()
    assert ov.geometry() == win._hud_cam_stack.rect()
    win.hud.state = "LISTENING"
    assert ov.state()[0] == "LISTENING"
    win.hud.speaking = True
    assert ov.state()[0] == "SPEAKING"
    ov.grab()
    win._hud_cam_stack.setCurrentIndex(0)
    assert ov.isHidden()


def test_missing_readings_are_hidden(win, monkeypatch):
    import ui.window as uw
    snap = {"cpu": 5.0, "mem": 40.0, "net": 0.1, "gpu": -1.0, "tmp": -1.0}
    monkeypatch.setattr(uw._metrics, "snapshot", lambda: dict(snap))
    win._update_metrics()
    assert win._bar_gpu.isHidden() and win._bar_tmp.isHidden()
    snap["gpu"] = 12.0
    win._update_metrics()
    assert not win._bar_gpu.isHidden()


def test_attached_file_shows_and_clears(win, tmp_path):
    f = tmp_path / "plan.pdf"
    f.write_bytes(b"%PDF-1.4")
    win.on_text_command = None
    win._on_file_selected(str(f))
    assert win._current_file == str(f) and not win._file_hint.isHidden()
    assert "plan.pdf" in win._file_hint.text()
    win._clear_file()
    assert win._current_file is None and win._file_hint.isHidden()


def test_footer_hint_collapses_after_first_launches(qapp, monkeypatch):
    import memory.config_manager as cm
    import ui.hud
    ui.hud._sfx = None
    from ui.window import MainWindow
    monkeypatch.setattr(cm, "bump_launch_count", lambda: MainWindow.FOOTER_HINT_LAUNCHES + 1)
    w = MainWindow("face.png")
    try:
        assert w._footer_hint.text().endswith("SHORTCUTS")
        assert "F4 MUTE" in w._footer_hint.toolTip()
    finally:
        w._browser.shutdown()
        w.deleteLater()


def test_browser_dark_toggle_persists(qapp, monkeypatch):
    import memory.config_manager as cm
    saved = []
    monkeypatch.setattr(cm, "get_browser_dark", lambda: True)
    monkeypatch.setattr(cm, "save_browser_dark", lambda v: saved.append(v))
    from ui.browser import HudBrowser
    b = HudBrowser()
    try:
        assert b._b_dark.isChecked()
        b._b_dark.setChecked(False)
        assert saved == [False] and b._dark is False
    finally:
        b.shutdown()


class _AliveThread:
    def is_alive(self):
        return True


def test_camera_feed_is_reused_not_reopened(win, monkeypatch):
    """A second camera question must not start another capture thread (it
    could not open the camera the first holds, and its exit would put the
    sphere back), and the snapshot comes from the live feed."""
    import threading
    import time
    win._cam_thread = _AliveThread()
    win._cam_stop.clear()
    win._cam_last = (b"jpeg-bytes", time.monotonic())
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    win.start_camera_stream()
    assert started == []                                   # reused
    assert win.camera_snapshot() == b"jpeg-bytes"
    win._cam_last = (b"old", time.monotonic() - 5)
    assert win.camera_snapshot() is None                   # stale frame: reopen instead
    win._cam_thread = None
    assert win.camera_snapshot() is None


def test_presence_card_has_a_live_sphere(win):
    win._hud_cam_stack.setCurrentIndex(1)
    ov = win._presence
    assert ov._sphere is not None
    r = ov.card_rect()
    assert r.right() < ov.width() and r.bottom() < ov.height()
    ov._tick()
    ov.grab()
    win._hud_cam_stack.setCurrentIndex(0)



def test_live_transcript_fills_in_and_finalises_without_duplicates(log, qapp):
    log.live("you", "open")
    log.live("you", "open my")
    _drain(qapp)
    assert len(log.entries()) == 1
    you = log.entries()[0].card
    assert you.body.text() == "open my" and you.live and you.when.text() == "● LIVE"
    log.append_log("[open_app] Mail")
    log.live("ai", "Opening")
    log.live("ai", "Opening your mail, sir.")
    _drain(qapp)
    assert len(log.entries()) == 2
    ai = log.entries()[1].card
    assert ai.body.text() == "Opening your mail, sir." and ai.live
    assert "open app" in ai.tools.text()                     # tools attach to the live card
    # the turn's final lines arrive: same cards, now final — nothing added
    log.append_log("You: open my email")
    log.append_log("JARVIS: Opening your mail, sir.")
    log.live("end", "")
    _drain(qapp)
    assert len(log.entries()) == 2
    assert you.body.text() == "open my email" and not you.live and not ai.live


def test_live_end_closes_cards_with_no_final_line(log, qapp):
    log.live("ai", "Half a sentence")
    log.live("end", "")
    _drain(qapp)
    card = log.entries()[0].card
    assert not card.live and card.body.text() == "Half a sentence"
    log.live("you", "next thing")                              # a fresh card, not the old one
    _drain(qapp)
    assert len(log.entries()) == 2


def test_typed_commands_still_get_their_own_card(log, qapp):
    log.live("you", "spoken words")
    log.append_log("YOU (terminal): status report")             # 'via' lines are separate
    _drain(qapp)
    assert len(log.entries()) == 2 and log.entries()[0].card.live



def _video_with_sound(win):
    win._video_on = True
    win._video_split = False
    if win._video_audio is None:
        pytest.skip("no video support in this Qt install")
    win._video_audio.setMuted(False)


def test_video_sound_keeps_the_mic_open_for_his_name(win):
    _video_with_sound(win)
    win.video_name_gate = lambda: True
    win._sync_mic_for_video()
    assert win._video_gate is True and win._muted is False     # not muted any more
    win._duck_video(True)
    assert win._video_ducked and abs(win._video_audio.volume() - 0.12) < 0.01
    win._video_audio.setMuted(True)                            # sound off: gate and duck end
    win._sync_mic_for_video()
    assert win._video_gate is False and not win._video_ducked
    assert abs(win._video_audio.volume() - 1.0) < 0.01


def test_without_the_name_model_video_sound_still_mutes(win):
    _video_with_sound(win)
    win.video_name_gate = lambda: False
    win._sync_mic_for_video()
    assert win._video_gate is False and win._muted is True and win._video_auto_muted
    win._video_audio.setMuted(True)
    win._sync_mic_for_video()
    assert win._muted is False
