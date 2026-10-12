"""
Screen & webcam capture for JARVIS vision.

Provides the two capture entry points main.py uses — `_capture_screen()` and
`_capture_camera()` — plus their helpers (compression, camera auto-detection,
config access). main.py grabs a frame here on demand, then injects it into the
main Gemini Live session; there is no separate vision session here.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        cfg = _load_config()
        cfg[key] = value
        _CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Vision] ⚠️  Could not save config key '{key}': {e}")


def _get_os() -> str:
    # The RUNNING system decides, not the setup screen's saved choice: a
    # config copied from another PC (or a mis-click) said 'windows' on Linux
    # and sent the camera to DirectShow. The saved value is only a fallback
    # for a platform Python does not recognise.
    import platform as _pf
    known = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}
    return known.get(_pf.system()) or _load_config().get("os_system", "linux").lower()


_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 82


def _compress(img_bytes: bytes, source_format: str = "PNG",
              max_size: tuple[int, int] = (_IMG_MAX_W, _IMG_MAX_H)) -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail(max_size, PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"


def _cursor_pos() -> tuple[int, int] | None:
    """Mouse position in virtual-desktop coordinates, or None if unknown."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y
        except Exception:
            pass
    try:
        import pyautogui  # type: ignore
        p = pyautogui.position()
        return int(p.x), int(p.y)
    except Exception:
        return None


def _pick_monitor(monitors: list[dict], which: str, cursor=None) -> tuple[dict, str]:
    """Choose a screen. `monitors` is mss's list ([0] = all screens combined,
    [1..n] = each screen). Returns (monitor, human label).

    which: "auto" (the screen under the mouse — where the user is looking),
           "all"/"both", "primary"/"main"/"1", "secondary"/"2", "3"…,
           "left", "right".
    The old code always took monitors[1], so a second screen was invisible.
    """
    screens = monitors[1:] or monitors[:1]
    n = len(screens)
    if n == 1:
        return screens[0], "the only screen"
    # mss ≥ 10 marks the primary screen; older versions: the one at (0, 0).
    # (mss does NOT list the primary first — on a stacked layout monitors[1]
    # can be the lower, secondary screen.)
    primary = next((m for m in screens if m.get("is_primary")), None) or \
        next((m for m in screens if m["left"] == 0 and m["top"] == 0), screens[0])
    others = sorted((m for m in screens if m is not primary), key=lambda m: (m["left"], m["top"]))
    w = (which or "auto").strip().lower()

    if w in ("all", "both", "everything", "every"):
        return monitors[0], f"all {n} screens together"
    if w in ("primary", "main", "1", "first"):
        return primary, f"the primary screen (1 of {n})"
    if w in ("secondary", "second", "other", "2"):
        return others[0], f"the secondary screen (2 of {n})"
    if w.isdigit() and 2 <= int(w) <= n:
        return others[int(w) - 2], f"screen {w} of {n}"
    if w == "left":
        m = min(screens, key=lambda m: m["left"])
        return m, f"the left screen ({n} total)"
    if w == "right":
        m = max(screens, key=lambda m: m["left"] + m["width"])
        return m, f"the right screen ({n} total)"
    if w in ("top", "upper", "above"):
        m = min(screens, key=lambda m: m["top"])
        return m, f"the top screen ({n} total)"
    if w in ("bottom", "lower", "below"):
        m = max(screens, key=lambda m: m["top"] + m["height"])
        return m, f"the bottom screen ({n} total)"

    # auto: the screen the mouse is on
    cursor = cursor if cursor is not None else _cursor_pos()
    if cursor:
        x, y = cursor
        for m in screens:
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                idx = 1 if m is primary else 2 + others.index(m)
                return m, f"screen {idx} of {n} (the one with the mouse)"
    return primary, f"the primary screen (1 of {n})"


def _capture_screen(which: str = "auto") -> tuple[bytes, str]:
    """Back-compatible: returns (bytes, mime). See capture_screen_labeled."""
    img, mime, _ = capture_screen_labeled(which)
    return img, mime


# Screenshot tools for Linux, tried in order when mss cannot see the screen.
# mss reads the X11 root window: on Wayland (the default on Ubuntu and Fedora)
# it either fails or returns an all-black image, so the desktop's own tool is
# used instead — grim (wlroots: Sway, Hyprland), gnome-screenshot (GNOME),
# spectacle (KDE), then X11 tools.
_LINUX_SHOT_TOOLS = (
    ("grim",             lambda f: ["grim", f]),
    ("gnome-screenshot", lambda f: ["gnome-screenshot", "-f", f]),
    ("spectacle",        lambda f: ["spectacle", "-b", "-n", "-f", "-o", f]),
    ("scrot",            lambda f: ["scrot", "-o", f]),
    ("import",           lambda f: ["import", "-window", "root", f]),
)


def _is_black(png: bytes) -> bool:
    """True for an (almost) all-black capture — what mss returns on Wayland."""
    if not _PIL:
        return False
    try:
        img = PIL.Image.open(io.BytesIO(png)).convert("L")
        img.thumbnail((160, 90))
        return max(img.getextrema()) < 8
    except Exception:
        return False


def _linux_tool_screenshot() -> bytes | None:
    """PNG of the whole desktop from the first screenshot tool that works."""
    import shutil
    import subprocess
    import tempfile
    for name, cmd in _LINUX_SHOT_TOOLS:
        if not shutil.which(name):
            continue
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            subprocess.run(cmd(path), capture_output=True, timeout=15)
            data = Path(path).read_bytes() if os.path.exists(path) else b""
            if data and not _is_black(data):
                return data
        except Exception:
            pass
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
    return None


def capture_screen_labeled(which: str = "auto") -> tuple[bytes, str, str]:
    """Capture a screen; returns (image bytes, mime type, which-screen label)."""
    png, label = None, ""
    if _MSS:
        try:
            factory = getattr(mss, "MSS", None) or mss.mss     # mss.mss is deprecated in mss ≥ 10
            with factory() as sct:
                target, label = _pick_monitor(sct.monitors, which)
                shot = sct.grab(target)
                png = mss.tools.to_png(shot.rgb, shot.size)
            if sys.platform.startswith("linux") and _is_black(png):
                png = None                                  # Wayland: mss sees nothing
        except Exception as e:
            if not sys.platform.startswith("linux"):
                raise
            print(f"[Vision] mss could not capture ({e}) — trying the desktop's screenshot tool")
            png = None
    if png is None and sys.platform.startswith("linux"):
        png = _linux_tool_screenshot()
        label = "all screens (desktop screenshot tool)"
        if png is None:
            raise RuntimeError(
                "Could not capture the screen. On Wayland install the desktop's screenshot "
                "tool: grim (Sway/Hyprland), gnome-screenshot (GNOME) or spectacle (KDE).")
    if png is None:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    # A stitched multi-screen image keeps more pixels so text stays legible
    # (long side up to 2560 — stacked layouts are taller than they are wide).
    size = (2560, 2560) if label.startswith("all ") else (_IMG_MAX_W, _IMG_MAX_H)
    img, mime = _compress(png, "PNG", max_size=size)
    return img, mime, label


def _cv2_backend() -> int:
    """The OpenCV camera backend for the running OS (see core/camera.py)."""
    from core import camera
    return camera.backend()


def _probe_camera(index: int, backend: int = 0, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    from core import camera
    try:
        cap = camera.open_camera(index, fallback=False)
    except camera.CameraError:
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    from core import camera
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in camera.candidate_indices():
        if _probe_camera(idx):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    # Not saved: a failure here is often temporary (no permission yet, camera
    # unplugged or busy), and saving 0 would stop it ever being looked for again.
    print(f"[Vision] ⚠️  No camera found — {camera.diagnose(0)}")
    return 0


def _get_camera_index() -> int:
    cfg = _load_config()
    if "camera_index" in cfg:
        return int(cfg["camera_index"])
    return _detect_camera_index()


def _capture_camera() -> tuple[bytes, str]:
    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    from core import camera
    # The live view already holds the camera (on Linux nobody else can open
    # it then): use its newest frame.
    frame = camera.latest()
    if frame is None:
        index = _get_camera_index()
        try:
            cap = camera.open_camera(index)
        except camera.CameraError as e:
            raise RuntimeError(f"The camera could not be opened: {e}")
        for _ in range(10):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"
