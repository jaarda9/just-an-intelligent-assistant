"""
Holo-Sphere — the HUD centrepiece: a globe of light that is JARVIS's presence.

~1,800 points on a Fibonacci sphere, rotating slowly. The state shapes it:

  idle       slow drift, a faint breathing pulse
  listening  breathes with the room — the microphone level swells it
  thinking   spins up; three tilted orbit rings carry bright data streams
  speaking   ripples run pole to pole, driven by the real voice level
  muted      dim, near-still, desaturated (colour comes from the caller)

Rendering is built for cost, not convenience. The old face made ~1,000 Python
draw calls a frame; this makes one. Every point is projected with numpy,
splatted into an intensity buffer with np.bincount, given a soft glow with a
separable box blur, colour-mapped to premultiplied ARGB and handed to Qt as a
single QImage. No GPU, no extra packages.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QRadialGradient, QBrush
from PyQt6.QtCore import Qt

_N = 1800
_GOLDEN = math.pi * (3.0 - math.sqrt(5.0))


def _fibonacci_sphere(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float32) + 0.5
    y = 1.0 - 2.0 * i / n
    rad = np.sqrt(1.0 - y * y)
    th = _GOLDEN * i
    return np.stack([np.cos(th) * rad, y, np.sin(th) * rad], axis=1).astype(np.float32)


def _box_blur(img: np.ndarray, r: int) -> np.ndarray:
    """Separable box blur via cumulative sums — O(pixels), radius-independent."""
    if r <= 0:
        return img
    k = 2 * r + 1
    p = np.pad(img, ((r + 1, r), (0, 0)), mode="constant")
    c = np.cumsum(p, axis=0)
    img = (c[k:] - c[:-k]) / k
    p = np.pad(img, ((0, 0), (r + 1, r)), mode="constant")
    c = np.cumsum(p, axis=1)
    return (c[:, k:] - c[:, :-k]) / k


class HoloSphere:
    def __init__(self, n: int = _N):
        self._base = _fibonacci_sphere(n)
        # polar angle from +Y — the axis the ripples travel along
        self._theta = np.arccos(np.clip(self._base[:, 1], -1, 1)).astype(np.float32)
        self._phi = np.arctan2(self._base[:, 2], self._base[:, 0]).astype(np.float32)
        self._yaw = 0.0
        self._t = 0.0
        self._amp = 0.0
        self._spin = 0.25          # rad/s, eased toward the state's target
        self._streams = 0.0        # 0..1 visibility of thinking orbit rings
        self._state = "IDLE"
        self._speaking = False
        self._muted = False
        # orbit rings: (tilt_x, tilt_z, radius, speed, phase)
        self._orbits = [(0.95, 0.30, 1.28, 1.3, 0.0),
                        (-0.55, 1.05, 1.36, -1.0, 2.1),
                        (0.25, -0.85, 1.44, 0.8, 4.2)]
        ang = np.linspace(0, 2 * np.pi, 220, endpoint=False, dtype=np.float32)
        self._ring = np.stack([np.cos(ang), np.zeros_like(ang), np.sin(ang)], axis=1)
        self._ring_ang = ang
        self._buf_key = None

    # ── animation ────────────────────────────────────────────────────────────
    def step(self, dt: float, amp: float, state: str, speaking: bool, muted: bool) -> None:
        dt = min(0.1, max(0.0, dt))
        self._t += dt
        self._state, self._speaking, self._muted = state, speaking, muted
        self._amp += (amp - self._amp) * min(1.0, dt * 14)
        thinking = state in ("THINKING", "PROCESSING")
        target = (0.05 if muted or state == "SLEEPING" else
                  1.6 if thinking else 0.55 if speaking else 0.25)
        self._spin += (target - self._spin) * min(1.0, dt * 2.5)
        self._yaw += self._spin * dt
        want = 1.0 if thinking else 0.0
        self._streams += (want - self._streams) * min(1.0, dt * 3.0)

    # ── rendering ────────────────────────────────────────────────────────────
    def _rotation(self) -> np.ndarray:
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        tilt = 0.38 + 0.05 * math.sin(self._t * 0.31)
        cx, sx = math.cos(tilt), math.sin(tilt)
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
        rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float32)
        return rx @ ry

    def _displacement(self) -> np.ndarray:
        t, amp = self._t, self._amp
        if self._muted or self._state == "SLEEPING":
            return 1.0 + 0.006 * np.sin(self._theta * 3 + t * 0.6)
        breathe = 0.012 * math.sin(t * 1.4)
        d = 1.0 + breathe
        if self._speaking:
            a = 0.018 + 0.075 * amp
            d = d + a * np.sin(self._theta * 9.0 - t * 7.5) \
                  + 0.25 * a * np.sin(self._phi * 4.0 + t * 3.0)
        else:
            d = d + 0.07 * amp * np.sin(self._theta * 6.0 - t * 4.0) \
                  + 0.010 * np.sin(self._phi * 5.0 + t * 1.1)
        if self._state in ("THINKING", "PROCESSING"):
            d = d + 0.018 * np.sin(self._theta * 14.0 + self._phi * 3.0 - t * 9.0)
        return d

    def _splat(self, buf: np.ndarray, xs, ys, w, size: int) -> None:
        xi = xs.astype(np.int32)
        yi = ys.astype(np.int32)
        ok = (xi >= 0) & (xi < size) & (yi >= 0) & (yi < size)
        idx = yi[ok] * size + xi[ok]
        buf += np.bincount(idx, weights=w[ok], minlength=size * size).reshape(size, size)

    # Rendered at half the on-screen resolution and scaled up smoothly: the
    # glow is soft anyway, the points come out as 2 px soft dots (which reads
    # better than 1 px pinpricks), and it is a quarter of the pixel work.
    SCALE = 0.5

    def _scale_for(self, r: float) -> float:
        # Small spheres (mini-mode) are cheap at full resolution and look
        # mushy at half; big ones use the half-res path.
        return self.SCALE if r >= 120 else 1.0

    def render(self, r: float, main: QColor, acc: QColor) -> QImage:
        """The sphere and its glow as a premultiplied ARGB image of side
        ~2.9r * scale (the caller draws it at 2.9r)."""
        r = r * self._scale_for(r)
        size = max(16, int(r * 2.9))
        half = size / 2.0
        buf = np.zeros((size, size), dtype=np.float32)

        R = self._rotation()
        pts = (self._base * self._displacement()[:, None]) @ R.T
        z = pts[:, 2]
        depth = np.clip((z + 1.2) / 2.4, 0.0, 1.0)          # 0 back … 1 front
        w = 0.22 + 0.78 * depth ** 1.6
        if self._speaking:
            w = w * (1.0 + 0.9 * self._amp)
        if self._muted:
            w = w * 0.45
        self._splat(buf, half + pts[:, 0] * r, half - pts[:, 1] * r, w.astype(np.float32), size)

        # thinking: orbit rings with a bright comet travelling along each
        if self._streams > 0.02:
            for k, (tx, tz, rad, spd, ph) in enumerate(self._orbits):
                cx_, sx_ = math.cos(tx), math.sin(tx)
                cz_, sz_ = math.cos(tz), math.sin(tz)
                rx = np.array([[1, 0, 0], [0, cx_, -sx_], [0, sx_, cx_]], dtype=np.float32)
                rz = np.array([[cz_, -sz_, 0], [sz_, cz_, 0], [0, 0, 1]], dtype=np.float32)
                ring = (self._ring * rad) @ (R @ rz @ rx).T
                head = (self._t * spd * 1.6 + ph) % (2 * np.pi)
                gap = (self._ring_ang - head) % (2 * np.pi)
                comet = np.exp(-gap * 2.2) * 4.0                 # tail behind the head
                rw = (0.10 + comet) * self._streams * (0.4 + 0.6 * (ring[:, 2] + 1.4) / 2.8)
                self._splat(buf, half + ring[:, 0] * r, half - ring[:, 1] * r,
                            rw.astype(np.float32), size)

        # glow: sharp points + a tight halo + a wide bloom
        # Normalise by point density (points per pixel ∝ N / r²), tuned at the
        # main HUD's size (1,800 points, buffer radius 85 px). Without this a
        # small sphere saturates into a white blob. The globe stays
        # see-through: only overlapping front points and comet heads run hot.
        density = (len(self._base) / 1800.0) / max(1e-3, (r / 85.0) ** 2)
        buf *= 0.5 / max(1.0, density) ** 0.6     # partial: the glow spreads light too
        glow = buf + _box_blur(buf, 1) * 1.6 \
                   + _box_blur(buf, max(2, int(r * 0.06))) * 6.0
        inten = np.clip(glow, 0.0, 1.6)

        a = np.minimum(inten, 1.0)
        hot = np.clip(inten - 1.0, 0.0, 0.6) * (1 / 0.6)         # >1 → toward white
        out = np.empty((size, size, 4), dtype=np.uint8)          # BGRA = ARGB32 LE
        a255 = a * 255.0
        for ch, val in ((0, acc.blue()), (1, acc.green()), (2, acc.red())):
            out[..., ch] = (val + (255 - val) * hot) * a
        out[..., 3] = a255
        self._last = out                                          # keep alive for Qt
        return QImage(out.data, size, size, size * 4,
                      QImage.Format.Format_ARGB32_Premultiplied)

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              main: QColor, acc: QColor, bg: QColor) -> None:
        # inner core light behind the points: gives the globe volume
        lift = 0.20 + 0.25 * self._amp + (0.12 if self._speaking else 0.0)
        if self._muted:
            lift *= 0.4
        g = QRadialGradient(cx, cy, r * 1.05)
        c0 = QColor(acc); c0.setAlphaF(min(1.0, lift))
        c1 = QColor(main); c1.setAlphaF(min(1.0, lift * 0.35))
        c2 = QColor(main); c2.setAlphaF(0.0)
        g.setColorAt(0.0, c0); g.setColorAt(0.45, c1); g.setColorAt(1.0, c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(cx - r * 1.05, cy - r * 1.05, r * 2.1, r * 2.1))
        p.setBrush(Qt.BrushStyle.NoBrush)

        img = self.render(r, main, acc)
        s = img.width() / self._scale_for(r)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(cx - s / 2, cy - s / 2, s, s), img)
        p.restore()
