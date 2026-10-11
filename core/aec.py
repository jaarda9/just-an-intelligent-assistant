"""
Acoustic echo cancellation for the microphone — so JARVIS can be interrupted
by voice on ordinary speakers.

The microphone hears JARVIS through the speakers. To tell a person talking
over him from his own echo, the echo has to be *removed*, not guessed at: the
WebRTC audio processing module (the canceller used by video calls, shipped
pre-built in the `livekit` package) is given everything he plays and
subtracts its echo from every microphone block, sample by sample. What is
left is the room — and the person, if they speak.

Measured on a room simulation (Windows TTS voices, 128 ms output buffer,
reverb, speaker loudness from quiet to louder-than-the-user): the canceller
removes 22-26 dB of echo once converged (about 3 s of his speech), keeps the
user's voice within ~2 dB, and the barge-in detector below caught a voice
talking over him in 9 of 9 cases (median 0.30 s) with no false triggers —
against 8 of 18 for the content/loudness guard in core/echo.py, which stays
as the fallback when `livekit` is not installed.

Threads: `render()` is called from the playback path, `capture()` from the
microphone callback. The processing module is built for exactly that split.
"""
from __future__ import annotations

import numpy as np

try:
    from livekit import rtc as _rtc
    HAVE_AEC = True
except Exception:                      # optional dependency
    _rtc = None
    HAVE_AEC = False

WARM_S = 3.0          # seconds of rendered speech before barge-in is trusted

# Barge-in on the cleaned signal: a block is "voice" when its level clears
# both an absolute floor and MULT x the level the leftover echo reaches here
# (90th percentile, learned while nobody talks); NEED of the last WINDOW blocks.
_ABS_MIN = 180.0      # RMS, int16
_MULT = 4.0
_NEED, _WINDOW = 3, 5
_START_BAR = 600.0    # until learned
# A person's voice survives the canceller almost whole (simulation: 78-89% of
# its level kept, median); a leak of JARVIS's own echo is mostly removed even
# when some of it gets through. A block must keep at least this share of its
# raw level to count as a voice.
_KEPT_MIN = 0.5


class EchoCanceller:
    def __init__(self, mic_sr: int, out_sr: int):
        self.mic_sr, self.out_sr = mic_sr, out_sr
        self.ok = False
        self._apm = None
        self._render_carry = np.zeros(0, dtype=np.int16)
        self.rendered_s = 0.0
        self._levels: list[float] = []
        self._hits: list[bool] = []
        self.last_rms = 0.0
        self.last_raw_rms = 0.0
        if HAVE_AEC:
            try:
                self._apm = _rtc.AudioProcessingModule(
                    echo_cancellation=True, noise_suppression=False,
                    high_pass_filter=True, auto_gain_control=False)
                self.ok = True
            except Exception as e:
                print(f"[AEC] unavailable: {e}")

    @property
    def warm(self) -> bool:
        return self.ok and self.rendered_s >= WARM_S

    # ── the two streams ─────────────────────────────────────────────────────
    def render(self, pcm) -> None:
        """Audio handed to the speakers (int16 at out_sr), any length."""
        if not self.ok:
            return
        try:
            x = np.asarray(pcm, dtype=np.int16).reshape(-1)
            if self._render_carry.size:
                x = np.concatenate([self._render_carry, x])
            n = self.out_sr // 100
            full = x.size // n * n
            for k in range(0, full, n):
                self._apm.process_reverse_stream(self._frame(self.out_sr, x[k:k + n]))
            self._render_carry = x[full:].copy()
            self.rendered_s += full / self.out_sr
        except Exception as e:
            print(f"[AEC] render failed, disabling: {e}")
            self.ok = False

    def capture(self, block):
        """A microphone block (int16 at mic_sr, a multiple of 10 ms) with the
        echo removed. Returns the input unchanged if cancellation is off."""
        x = np.asarray(block, dtype=np.int16).reshape(-1)
        if not self.ok:
            return x
        n = self.mic_sr // 100
        if x.size % n:
            return x
        try:
            out = np.empty_like(x)
            for k in range(0, x.size, n):
                f = self._frame(self.mic_sr, x[k:k + n])
                self._apm.process_stream(f)
                out[k:k + n] = np.frombuffer(f.data, dtype=np.int16)
            self.last_rms = float(np.sqrt(np.mean(out.astype(np.float32) ** 2)))
            self.last_raw_rms = float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))
            return out
        except Exception as e:
            print(f"[AEC] capture failed, disabling: {e}")
            self.ok = False
            return x

    @staticmethod
    def _frame(sr: int, pcm):
        f = _rtc.AudioFrame.create(sr, 1, pcm.size)
        np.frombuffer(f.data, dtype=np.int16)[:] = pcm
        return f

    # ── barge-in ────────────────────────────────────────────────────────────
    def bar(self) -> float:
        if len(self._levels) >= 20:
            return max(_ABS_MIN, _MULT * float(np.percentile(self._levels, 90)))
        return max(_ABS_MIN, _START_BAR)

    def voice_now(self, rms: float | None = None, raw: float | None = None) -> bool:
        """Feed one cleaned block's level (while JARVIS speaks). True once the
        recent blocks say a person is talking over him."""
        rms = self.last_rms if rms is None else rms
        raw = self.last_raw_rms if raw is None else raw
        kept = rms / max(raw, 1.0)
        hit = rms >= self.bar() and kept >= _KEPT_MIN
        if not hit:
            self._levels.append(rms)
            if len(self._levels) > 300:
                del self._levels[:-300]
        self._hits.append(hit)
        del self._hits[:-_WINDOW]
        if sum(self._hits) >= _NEED:
            self._hits.clear()
            return True
        return False

    def reset_votes(self) -> None:
        self._hits.clear()

    def stats(self) -> str:
        return (f"AEC {'warm' if self.warm else f'warming {self.rendered_s:.1f}/{WARM_S:.0f}s'}, "
                f"voice bar {self.bar():.0f} rms")
