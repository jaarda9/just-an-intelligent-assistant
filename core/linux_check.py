"""
Startup check for Linux: which features will work, and what to install for
the ones that will not.

On Windows almost everything JARVIS controls is built into the OS. On Linux
it leans on small system tools — playerctl for media, pactl for volume, a
screenshot tool on Wayland — that a fresh install may not have, and without
them the feature just quietly does nothing. This lists what is missing, once
at startup, with the package to install (Debian/Ubuntu names; Fedora and Arch
use the same names for these).
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil


def _have(*tools: str) -> bool:
    return any(shutil.which(t) for t in tools)


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def check() -> list[tuple[str, str]]:
    """[(what does not work, how to fix it)] — empty when all is well."""
    if platform.system() != "Linux":
        return []
    from core import camera
    from core.linux_keys import session_type
    out: list[tuple[str, str]] = []
    wayland = session_type() == "wayland"

    devs = camera.linux_devices()
    if not devs:
        out.append(("camera", "no /dev/video* device found — connect a webcam"))
    elif not any(os.access(d, os.R_OK | os.W_OK) for d in devs):
        out.append(("camera", "no permission — sudo usermod -aG video $USER, then log out and in"))

    if not _have("playerctl"):
        out.append(("media control / Now Playing", "sudo apt install playerctl"))
    if not _have("pactl"):
        out.append(("volume control", "sudo apt install pulseaudio-utils"))
    if not _have("brightnessctl"):
        out.append(("screen brightness", "sudo apt install brightnessctl"))
    if not _have("xdg-open"):
        out.append(("opening links and files", "sudo apt install xdg-utils"))
    if not _have("notify-send"):
        out.append(("reminder pop-ups", "sudo apt install libnotify-bin"))
    if not _have("systemd-run", "at"):
        out.append(("scheduled reminders", "sudo apt install at"))

    if wayland:
        if not _have("grim", "gnome-screenshot", "spectacle"):
            out.append(("screen capture (Wayland)",
                        "install your desktop's tool: gnome-screenshot (GNOME), "
                        "spectacle (KDE) or grim (Sway/Hyprland)"))
        if not _have("wl-copy"):
            out.append(("clipboard", "sudo apt install wl-clipboard"))
    else:
        if not _have("xclip", "xsel"):
            out.append(("clipboard", "sudo apt install xclip"))
        if not _module("pynput"):
            out.append(("Ctrl+Alt+J and push-to-talk from other windows",
                        "pip install pynput (in JARVIS's .venv)"))

    if not _module("livekit"):
        out.append(("echo cancellation (talking over JARVIS)",
                    "pip install livekit (in JARVIS's .venv)"))
    try:
        from core import wake_word
        if not wake_word.is_ready():
            out.append(("interrupt by saying 'Jarvis'",
                        "pip install openwakeword (in JARVIS's .venv), then restart"))
    except Exception:
        pass
    return out


def notes() -> list[str]:
    """Limits of the platform that no package removes."""
    if platform.system() != "Linux":
        return []
    from core.linux_keys import session_type
    if session_type() == "wayland":
        return ["Wayland: Ctrl+Alt+J and push-to-talk work only while JARVIS's window "
                "is focused, and typing/clicking for you reaches only X11 apps. "
                "Log in with an X11 (Xorg) session to lift both."]
    return []


def report(log=print) -> int:
    """Print the check; returns the number of missing pieces."""
    missing = check()
    for what, fix in missing:
        log(f"[Linux] ⚠️  {what}: {fix}")
    for n in notes():
        log(f"[Linux] ℹ️  {n}")
    if not missing:
        log("[Linux] ✅ all helper tools present")
    return len(missing)
