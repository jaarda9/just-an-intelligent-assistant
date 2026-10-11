"""
Interface sound effects — the small chirps and tones that make the HUD feel
like a system rather than a chat window.

Every sound is synthesised here from sine partials (no bundled audio, nothing
to license) and written once to config/sfx/*.wav. Playback is fire-and-forget
and never raises: a missing audio device must not cost the user their
assistant.

  Windows  — winsound (async, mixes alongside the Live voice stream).
  Others   — sounddevice in a short-lived thread.

Toggle with "sfx_enabled": false in config/api_keys.json.
"""
from __future__ import annotations

import platform
import threading
import time
import wave
from pathlib import Path

import numpy as np

_SR = 44100
_PEAK = 0.20                 # quiet on purpose — these sit under the voice
_DIR = Path(__file__).resolve().parent.parent / "config" / "sfx"
_OS = platform.system()

# Minimum gap per sound, so a burst of tool calls is one tick, not a rattle.
_MIN_GAP = {"tick": 0.5, "done": 0.8}
_last_play: dict[str, float] = {}
_built = False
_build_lock = threading.Lock()

_cfg_cache: tuple[float, bool] = (0.0, True)


# ── synthesis ────────────────────────────────────────────────────────────────

def _env(n: int, attack: float = 0.005, release: float = 0.04) -> np.ndarray:
    a = max(1, int(_SR * attack))
    r = max(1, int(_SR * release))
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


def _tone(freq: float, dur: float, harmonics=(1.0, 0.3, 0.1), **env) -> np.ndarray:
    t = np.arange(int(_SR * dur)) / _SR
    sig = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harmonics))
    return sig * _env(len(t), **env)


def _sweep(f0: float, f1: float, dur: float, **env) -> np.ndarray:
    t = np.arange(int(_SR * dur)) / _SR
    # exponential glide: sounds even across the octave span
    f = f0 * (f1 / f0) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(f) / _SR
    sig = np.sin(phase) + 0.25 * np.sin(2 * phase)
    return sig * _env(len(t), **env)


def _gap(dur: float) -> np.ndarray:
    return np.zeros(int(_SR * dur))


def _mix(*layers: np.ndarray) -> np.ndarray:
    n = max(len(x) for x in layers)
    out = np.zeros(n)
    for x in layers:
        out[:len(x)] += x
    return out


def _designs() -> dict[str, np.ndarray]:
    boot_sweep = _sweep(180, 880, 0.70, attack=0.05, release=0.10)
    chord = _mix(*(_tone(f, 0.9, (1.0, 0.15), attack=0.02, release=0.6)
                   for f in (440, 554.37, 659.25, 880)))
    return {
        # rising sweep that resolves into a bright A-major chord
        "boot":  np.concatenate([boot_sweep, chord * 0.6]),
        # two quick rising blips — "I'm listening"
        "wake":  np.concatenate([_tone(880, 0.06), _gap(0.02), _tone(1320, 0.08)]),
        # a single soft high click when a tool starts
        "tick":  _tone(1760, 0.035, (1.0, 0.2), attack=0.002, release=0.025) * 0.6,
        # a gentle falling pair when the work is finished
        "done":  np.concatenate([_tone(1318.5, 0.07), _gap(0.015), _tone(987.8, 0.11, release=0.08)]) * 0.7,
        # a slow downward glide into sleep
        "sleep": _sweep(660, 300, 0.40, attack=0.01, release=0.15) * 0.8,
        # two-tone, twice — attention without alarm
        "alert": np.concatenate([_tone(880, 0.12), _tone(660, 0.12), _gap(0.06),
                                 _tone(880, 0.12), _tone(660, 0.16)]),
    }


def _write(path: Path, sig: np.ndarray) -> None:
    sig = sig / max(1e-9, float(np.max(np.abs(sig)))) * _PEAK
    pcm = (sig * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes(pcm.tobytes())


def _ensure_built() -> None:
    global _built
    if _built:
        return
    with _build_lock:
        if _built:
            return
        _DIR.mkdir(parents=True, exist_ok=True)
        for name, sig in _designs().items():
            p = _DIR / f"{name}.wav"
            if not p.exists():
                _write(p, sig)
        _built = True


# ── playback ─────────────────────────────────────────────────────────────────

def enabled() -> bool:
    global _cfg_cache
    now = time.monotonic()
    if now - _cfg_cache[0] < 5.0:
        return _cfg_cache[1]
    try:
        from memory.config_manager import load_api_keys
        on = bool(load_api_keys().get("sfx_enabled", True))
    except Exception:
        on = True
    _cfg_cache = (now, on)
    return on


def _play_file(path: Path) -> None:
    if _OS == "Windows":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
        return
    import sounddevice as sd
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    sd.play(data.astype(np.float32) / 32767, _SR)


def play(name: str) -> None:
    """Fire-and-forget. Unknown names, a muted config or a dead audio device
    are all silent no-ops."""
    try:
        if not enabled():
            return
        now = time.monotonic()
        if now - _last_play.get(name, 0.0) < _MIN_GAP.get(name, 0.0):
            return
        _last_play[name] = now
    except Exception:
        return

    def _go():
        try:
            _ensure_built()
            path = _DIR / f"{name}.wav"
            if path.exists():
                _play_file(path)
        except Exception as e:
            print(f"[SFX] {name}: {e}")

    threading.Thread(target=_go, daemon=True, name=f"sfx-{name}").start()


def on_state_change(prev: str, new: str) -> None:
    """Map HUD state transitions to sounds. Only meaningful edges make a
    sound — the every-turn SPEAKING→LISTENING flip stays silent, or the
    chirps would become noise inside ten minutes."""
    if prev == new:
        return
    if new == "THINKING":
        play("tick")
    elif new == "SLEEPING":
        play("sleep")
    elif new == "LISTENING" and prev in ("SLEEPING", "MUTED", "OFFLINE", "RECONNECTING"):
        play("wake")
    elif new == "LISTENING" and prev == "THINKING":
        play("done")
