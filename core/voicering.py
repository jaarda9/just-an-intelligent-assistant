"""
Voice Ring — the minimal centrepiece: one luminous ring that bends with the
voice, framed by thin orbit lines.

The ring is a closed polyline whose radius is modulated by a few travelling
sine waves; their amplitude is the live audio level, so speech visibly shapes
it. Glow is three strokes of the same path at falling width and opacity —
three draw calls, no per-pixel work. Same step()/paint() interface as the
Holo-Sphere, so the HUD treats the two interchangeably.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient, QBrush

_N = 240


class VoiceRing:
    def __init__(self):
        self._ang = np.linspace(0, 2 * np.pi, _N, endpoint=False)
        self._t = 0.0
        self._amp = 0.0
        self._spin = 0.0
        self._rate = 0.2
        self._state, self._speaking, self._muted = "IDLE", False, False
        self.assemble = 1.0          # boot: the ring draws itself on
        self.deep = False            # deep idle (set by the HUD): slower turn

    def step(self, dt: float, amp: float, state: str, speaking: bool, muted: bool) -> None:
        dt = min(0.1, max(0.0, dt))
        self._t += dt
        self._state, self._speaking, self._muted = state, speaking, muted
        self._amp += (amp - self._amp) * min(1.0, dt * 16)
        thinking = state in ("THINKING", "PROCESSING")
        target = 0.03 if (muted or state == "SLEEPING") else 1.4 if thinking else \
            0.35 if speaking else 0.1 if self.deep else 0.2
        self._rate += (target - self._rate) * min(1.0, dt * 3)
        self._spin += self._rate * dt

    def _path(self, cx: float, cy: float, r: float) -> QPainterPath:
        t, a = self._t, self._amp
        if self._muted or self._state == "SLEEPING":
            d = 0.004 * np.sin(self._ang * 3 + t * 0.5)
        else:
            k = (0.012 + 0.11 * a) if self._speaking else (0.006 + 0.05 * a)
            d = k * (np.sin(self._ang * 5 + t * 5.5)
                     + 0.6 * np.sin(self._ang * 9 - t * 7.3)
                     + 0.35 * np.sin(self._ang * 14 + t * 11.0))
            d = d + 0.008 * math.sin(t * 1.3)                    # breathing
        rr = r * (1.0 + d)
        span = max(1, int(_N * min(1.0, self.assemble)))
        xs = cx + rr[:span] * np.cos(self._ang[:span] + self._spin * 0.15)
        ys = cy + rr[:span] * np.sin(self._ang[:span] + self._spin * 0.15)
        path = QPainterPath(QPointF(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(x, y)
        if span == _N:
            path.closeSubpath()
        return path

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              main: QColor, acc: QColor, bg: QColor) -> None:
        p.save()
        # soft light inside the ring
        g = QRadialGradient(cx, cy, r * 1.1)
        c0 = QColor(acc); c0.setAlphaF(0.10 + 0.18 * self._amp)
        c1 = QColor(acc); c1.setAlphaF(0.0)
        g.setColorAt(0.0, c0); g.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r * 1.1, r * 1.1)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # orbit lines: thin tilted ellipses, turning with the state's rate
        for k, (tilt, scale, alpha) in enumerate(((0.30, 1.32, 0.35), (-0.55, 1.48, 0.22),
                                                  (1.10, 1.62, 0.15))):
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(self._spin * (0.6 + 0.25 * k) * (1 if k % 2 == 0 else -1)))
            c = QColor(main); c.setAlphaF(alpha)
            p.setPen(QPen(c, 1.0))
            p.drawEllipse(QRectF(-r * scale, -r * scale * (0.30 + 0.12 * k),
                                 r * scale * 2, r * scale * 2 * (0.30 + 0.12 * k)))
            # a bright node riding each orbit
            ang = self._spin * (1.2 + 0.4 * k) + k * 2.1
            nx = r * scale * math.cos(ang)
            ny = r * scale * (0.30 + 0.12 * k) * math.sin(ang)
            nc = QColor(acc); nc.setAlphaF(min(1.0, alpha * 2.4))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(nc)
            p.drawEllipse(QPointF(nx, ny), 2.4, 2.4)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.restore()

        # the ring: three strokes of one path → glow without per-pixel work
        path = self._path(cx, cy, r)
        lift = 1.0 + 0.8 * self._amp
        for width, alpha in ((r * 0.10, 0.06), (r * 0.035, 0.22), (2.2, 0.95)):
            c = QColor(acc); c.setAlphaF(min(1.0, alpha * lift) * (0.4 if self._muted else 1.0))
            pen = QPen(c, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(path)
        p.restore()
