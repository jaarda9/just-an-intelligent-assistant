"""Linux paths, exercised on any OS by faking the platform and the system.

Covers the camera (backend, device paths, permission advice, frame sharing),
the OS lookups (the running system wins over the saved setup choice), the
Wayland screenshot fallback, X11 global keys, and the startup check."""
import types as _t

import numpy as np
import pytest


# ── camera ───────────────────────────────────────────────────────────────────

@pytest.fixture
def linux_camera(monkeypatch):
    from core import camera
    monkeypatch.setattr(camera, "_OS", "Linux")
    return camera


def test_linux_uses_v4l2(linux_camera):
    cv2 = pytest.importorskip("cv2")
    assert linux_camera.backend() == cv2.CAP_V4L2


def test_device_list_is_numeric_order(linux_camera, monkeypatch):
    monkeypatch.setattr(linux_camera.glob, "glob",
                        lambda pat: ["/dev/video10", "/dev/video2", "/dev/video0"])
    assert linux_camera.linux_devices() == ["/dev/video0", "/dev/video2", "/dev/video10"]
    assert linux_camera.candidate_indices() == [0, 2, 10]


def test_advice_for_no_device_and_no_permission(linux_camera, monkeypatch):
    monkeypatch.setattr(linux_camera, "HAVE_CV2", True)
    monkeypatch.setattr(linux_camera.glob, "glob", lambda pat: [])
    assert "no camera device" in linux_camera.diagnose()
    monkeypatch.setattr(linux_camera.glob, "glob", lambda pat: ["/dev/video0"])
    monkeypatch.setattr(linux_camera.os, "access", lambda p, m: False)
    assert "'video' group" in linux_camera.diagnose()
    monkeypatch.setattr(linux_camera.os, "access", lambda p, m: True)
    assert "in use" in linux_camera.diagnose()


def test_open_tries_index_then_device_path(linux_camera, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    tried = []

    class Cap:
        def __init__(self, src, be):
            tried.append((src, be))
            self.ok = src == "/dev/video0"

        def isOpened(self):
            return self.ok

        def release(self):
            pass
    monkeypatch.setattr(linux_camera.cv2, "VideoCapture", Cap)
    monkeypatch.setattr(linux_camera.os.path, "exists", lambda p: True)
    cap = linux_camera.open_camera(0)
    assert cap.ok and tried == [(0, cv2.CAP_V4L2), ("/dev/video0", cv2.CAP_V4L2)]


def test_open_falls_back_to_another_camera(linux_camera, monkeypatch):
    """A saved camera that is gone (a phone webcam on /dev/video0) must not
    hide the built-in one; detection, asking about one index, gets no fallback."""
    pytest.importorskip("cv2")

    class Cap:
        def __init__(self, src, be):
            self.src = src
            self.ok = src == 1

        def isOpened(self):
            return self.ok

        def release(self):
            pass
    monkeypatch.setattr(linux_camera.cv2, "VideoCapture", Cap)
    monkeypatch.setattr(linux_camera.glob, "glob",
                        lambda pat: ["/dev/video0", "/dev/video1", "/dev/video2"])
    assert linux_camera.open_camera(0).src == 1
    with pytest.raises(linux_camera.CameraError):
        linux_camera.open_camera(0, fallback=False)


def test_open_failure_explains(linux_camera, monkeypatch):
    pytest.importorskip("cv2")

    class Never:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return False

        def release(self):
            pass
    monkeypatch.setattr(linux_camera.cv2, "VideoCapture", Never)
    monkeypatch.setattr(linux_camera.glob, "glob", lambda pat: ["/dev/video0"])
    monkeypatch.setattr(linux_camera.os, "access", lambda p, m: False)
    with pytest.raises(linux_camera.CameraError, match="video"):
        linux_camera.open_camera(0)


def test_live_frames_are_shared_and_expire(monkeypatch):
    from core import camera
    camera.clear()
    assert camera.latest() is None
    f = np.zeros((4, 4, 3), np.uint8)
    camera.publish(f)
    assert camera.latest() is f
    t0 = camera.time.monotonic()
    monkeypatch.setattr(camera.time, "monotonic", lambda: t0 + 5)
    assert camera.latest(max_age=1.0) is None
    camera.clear()


def test_snapshot_uses_the_live_frame(monkeypatch):
    pytest.importorskip("cv2")
    from actions import screen_processor as sp
    from core import camera
    frame = np.full((48, 64, 3), 120, np.uint8)
    camera.publish(frame)
    monkeypatch.setattr(camera, "open_camera",
                        lambda *a: (_ for _ in ()).throw(AssertionError("reopened the camera")))
    try:
        img, mime = sp._capture_camera()
        assert mime == "image/jpeg" and img[:2] == b"\xff\xd8"
    finally:
        camera.clear()


# ── OS lookups ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("system,expect", [("Linux", "linux"), ("Windows", "windows"),
                                           ("Darwin", "mac")])
def test_running_system_wins_over_saved_choice(monkeypatch, system, expect):
    import platform
    import config as cfg_mod
    from actions import computer_control, screen_processor, send_message
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: {"os_system": "windows-or-whatever"})
    monkeypatch.setattr(computer_control, "_load_config", lambda: {"os_system": "nonsense"})
    monkeypatch.setattr(screen_processor, "_load_config", lambda: {"os_system": "nonsense"})
    assert cfg_mod.get_os() == expect
    assert computer_control._get_os() == expect
    assert screen_processor._get_os() == expect
    assert send_message._get_os() == expect


# ── Wayland screenshots ──────────────────────────────────────────────────────

def _png(colour):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(b, format="PNG")
    return b.getvalue()


def test_black_mss_capture_falls_back_to_the_desktop_tool(monkeypatch):
    from actions import screen_processor as sp
    monkeypatch.setattr(sp.sys, "platform", "linux")

    class Shot:
        rgb, size = b"", (64, 36)

    class Sct:
        monitors = [{"left": 0, "top": 0, "width": 64, "height": 36},
                    {"left": 0, "top": 0, "width": 64, "height": 36, "is_primary": True}]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def grab(self, m):
            return Shot()
    monkeypatch.setattr(sp, "_MSS", True)
    monkeypatch.setattr(sp, "mss", _t.SimpleNamespace(
        MSS=Sct, tools=_t.SimpleNamespace(to_png=lambda rgb, size: _png((0, 0, 0)))))
    monkeypatch.setattr(sp, "_linux_tool_screenshot", lambda: _png((90, 140, 200)))
    img, mime, label = sp.capture_screen_labeled("auto")
    assert "screenshot tool" in label and img


def test_no_tool_on_wayland_says_what_to_install(monkeypatch):
    from actions import screen_processor as sp
    monkeypatch.setattr(sp.sys, "platform", "linux")
    monkeypatch.setattr(sp, "_MSS", False)
    monkeypatch.setattr(sp, "_linux_tool_screenshot", lambda: None)
    with pytest.raises(RuntimeError, match="gnome-screenshot"):
        sp.capture_screen_labeled("auto")


def test_is_black():
    from actions import screen_processor as sp
    assert sp._is_black(_png((0, 0, 0))) and not sp._is_black(_png((200, 200, 200)))


# ── keys ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env,expect", [
    ({"XDG_SESSION_TYPE": "wayland"}, "wayland"),
    ({"XDG_SESSION_TYPE": "x11"}, "x11"),
    ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
    ({"DISPLAY": ":0"}, "x11")])
def test_session_type(monkeypatch, env, expect):
    from core import linux_keys
    monkeypatch.setattr(linux_keys.platform, "system", lambda: "Linux")
    for k in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert linux_keys.session_type() == expect


def test_no_global_keys_on_wayland(monkeypatch):
    from core import linux_keys
    monkeypatch.setattr(linux_keys, "session_type", lambda: "wayland")
    assert linux_keys.global_keys_available() is False


def test_chord_watcher_tracks_press_and_release():
    from core.linux_keys import ChordWatcher
    seen = []
    w = ChordWatcher(("ctrl", "space"), seen.append)
    w._map = {"ctrl": {"CTRL_L"}, "space": {"SPACE"}}
    w._press("CTRL_L")
    assert seen == []
    w._press("SPACE")
    assert seen == [True]
    w._press("x")                                 # unrelated key: ignored
    w._release("CTRL_L")
    assert seen == [True, False]


def test_summon_falls_back_to_window_without_global_keys(monkeypatch):
    from core import linux_keys, summon
    monkeypatch.setattr(summon, "_OS", "Linux")
    monkeypatch.setattr(linux_keys, "global_keys_available", lambda: False)
    hk = summon.GlobalHotkey(lambda: None)
    assert hk.start() == "window"


def test_summon_goes_global_on_x11(monkeypatch):
    from core import linux_keys, summon
    monkeypatch.setattr(summon, "_OS", "Linux")
    monkeypatch.setattr(linux_keys, "global_keys_available", lambda: True)
    started = []
    monkeypatch.setattr(linux_keys.HotkeyPress, "start", lambda self: started.append(1) or True)
    monkeypatch.setattr(linux_keys.HotkeyPress, "stop", lambda self: None)
    hk = summon.GlobalHotkey(lambda: None)
    assert hk.start() == "global" and started
    hk.stop()
    assert hk.scope == "window"


# ── startup check ────────────────────────────────────────────────────────────

def test_linux_check_names_missing_tools(monkeypatch):
    from core import camera, linux_check, linux_keys
    monkeypatch.setattr(linux_check.platform, "system", lambda: "Linux")
    monkeypatch.setattr(linux_check.shutil, "which", lambda t: None)
    monkeypatch.setattr(camera, "linux_devices", lambda: ["/dev/video0"])
    monkeypatch.setattr(linux_check.os, "access", lambda p, m: False)
    monkeypatch.setattr(linux_keys, "session_type", lambda: "wayland")
    found = dict(linux_check.check())
    assert "video" in found["camera"]
    assert "playerctl" in found["media control / Now Playing"]
    assert "screen capture (Wayland)" in found and "clipboard" in found
    assert linux_check.notes() and "Wayland" in linux_check.notes()[0]


def test_linux_check_is_silent_elsewhere(monkeypatch):
    from core import linux_check
    monkeypatch.setattr(linux_check.platform, "system", lambda: "Windows")
    assert linux_check.check() == [] and linux_check.notes() == []
