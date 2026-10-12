"""
One place that opens the webcam, for every feature that needs it: the vision
snapshot, the live camera view in the HUD, and presence detection.

Per OS it picks the capture backend that actually works there — DirectShow on
Windows, AVFoundation on macOS, V4L2 on Linux (OpenCV's automatic choice on
Linux can land on a GStreamer pipeline that never delivers a frame) — and on
Linux also tries the /dev/videoN path directly. When nothing opens it says
why, in words a person can act on: no device, no permission (the usual Linux
case: the user is not in the 'video' group), or the camera is busy.

Linux lets one process hold a camera at a time, so while the live view is
streaming its newest frame is published here and the other features read
that instead of opening the device a second time (which would fail with
"device busy", or knock the live view out).
"""
from __future__ import annotations

import glob
import os
import platform
import threading
import time

_OS = platform.system()

try:
    import cv2  # type: ignore
    HAVE_CV2 = True
except Exception:
    cv2 = None
    HAVE_CV2 = False


class CameraError(RuntimeError):
    """The camera could not be opened; the message says why."""


def backend() -> int:
    if not HAVE_CV2:
        return 0
    if _OS == "Windows":
        return cv2.CAP_DSHOW
    if _OS == "Darwin":
        return cv2.CAP_AVFOUNDATION
    return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)


def linux_devices() -> list[str]:
    """/dev/videoN nodes, in number order (empty off Linux)."""
    if _OS != "Linux":
        return []
    def num(p):
        try:
            return int(p.rsplit("video", 1)[1])
        except ValueError:
            return 1 << 30
    return sorted(glob.glob("/dev/video*"), key=num)


def diagnose(index: int = 0) -> str:
    """Why a camera would not open, as advice (best effort)."""
    if not HAVE_CV2:
        return "OpenCV is not installed (pip install opencv-python)."
    if _OS == "Linux":
        devs = linux_devices()
        if not devs:
            return ("no camera device found (/dev/video* is empty) — is a webcam "
                    "connected, and is its driver loaded?")
        unreadable = [d for d in devs if not os.access(d, os.R_OK | os.W_OK)]
        if unreadable and len(unreadable) == len(devs):
            return ("no permission to use the camera — add yourself to the 'video' "
                    "group (sudo usermod -aG video $USER), then log out and back in.")
        return (f"camera {index} would not open — it may be in use by another app "
                f"(found: {', '.join(devs)}).")
    return f"camera {index} would not open — it may be in use by another app."


def open_camera(index: int = 0, fallback: bool = True):
    """An opened cv2.VideoCapture, or CameraError explaining why not.

    With `fallback` (the default) a Linux machine whose chosen camera will not
    open tries its other cameras before giving up. The saved index can point at
    a camera that comes and goes — a phone-as-webcam app such as Iriun or
    DroidCam registers /dev/video0 ahead of the built-in camera, and it opens
    only while the phone is connected — and without this every feature failed
    with the laptop's own camera sitting right there. The saved choice is left
    alone, so the preferred camera is still used whenever it is back.
    Auto-detection passes fallback=False: it is asking about ONE index."""
    if not HAVE_CV2:
        raise CameraError(diagnose(index))
    attempts = [(index, backend())]
    if _OS == "Linux":
        dev = f"/dev/video{index}"
        if os.path.exists(dev):
            attempts.append((dev, backend()))
        attempts.append((index, cv2.CAP_ANY))
    elif index != 0:
        attempts.append((0, backend()))
    for src, be in attempts:
        try:
            cap = cv2.VideoCapture(src, be)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception:
            pass
    if fallback and _OS == "Linux":
        for other in candidate_indices():
            if other == index:
                continue
            try:
                cap = cv2.VideoCapture(other, backend())
                if cap.isOpened():
                    print(f"[Camera] camera {index} would not open — using camera {other}")
                    return cap
                cap.release()
            except Exception:
                pass
    raise CameraError(diagnose(index))


def candidate_indices() -> list[int]:
    """Indices worth probing when looking for the webcam."""
    if _OS == "Linux":
        idx = []
        for d in linux_devices():
            try:
                idx.append(int(d.rsplit("video", 1)[1]))
            except ValueError:
                pass
        return idx[:8] or [0]
    return list(range(6))


# ── frames shared from the live view ─────────────────────────────────────────
_lock = threading.Lock()
_latest = None            # (bgr ndarray, monotonic time)


def publish(frame) -> None:
    """The live view's newest frame (BGR ndarray). Called per frame."""
    global _latest
    with _lock:
        _latest = (frame, time.monotonic())


def clear() -> None:
    global _latest
    with _lock:
        _latest = None


def latest(max_age: float = 1.0):
    """The live view's newest frame if it is fresh, else None."""
    with _lock:
        item = _latest
    if item is None or time.monotonic() - item[1] > max_age:
        return None
    return item[0]
