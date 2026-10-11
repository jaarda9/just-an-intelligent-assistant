"""
Keeps JARVIS visible while the browser, a video or the camera has the centre
of the HUD: his hologram moves aside into a small card in the bottom-right
corner — a live mini Holo-Sphere with his state under it — and a thin glowing
edge runs around the page while he speaks. The content stays where it is.

It floats over the centre stack as a plain child (not a stack page), ignores
the mouse entirely, and only repaints while one of those pages is showing.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRegion
from PyQt6.QtWidgets import QWidget

from .base import C, FONT_UI, qcol

CARD_W, CARD_H = 112, 120
MARGIN_X, MARGIN_Y = 22, 14   # clear of a page's scrollbar
SPHERE_R = 30                 # mini sphere radius (px)
EDGE = 3                      # px of glow around the page while speaking


class PresenceOverlay(QWidget):
    def __init__(self, stack, hud):
        super().__init__(stack)
        self._stack, self._hud = stack, hud
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._sphere = None                    # built on first show
        self._last = time.monotonic()
        self._was_speaking = False
        self._tmr = QTimer(self)
        self._tmr.setTimerType(Qt.TimerType.PreciseTimer)
        self._tmr.setInterval(33)              # ~30 fps; the mini sphere is cheap
        self._tmr.timeout.connect(self._tick)
        stack.installEventFilter(self)
        stack.currentChanged.connect(lambda _i: self.sync())
        self.sync()

    # ── visibility ───────────────────────────────────────────────────────────
    def sync(self) -> None:
        """Show over anything but the HUD itself (page 0)."""
        on = self._stack.currentIndex() != 0
        self.setGeometry(self._stack.rect())
        self.setVisible(on)
        if on:
            if self._sphere is None:
                try:
                    from core.holosphere import HoloSphere
                    self._sphere = HoloSphere(n=520)       # fewer points: it is small
                except Exception:
                    self._sphere = None                    # the orb fallback is drawn
            self._last = time.monotonic()
            self.raise_()
            self._tmr.start()
        else:
            self._tmr.stop()

    def eventFilter(self, obj, ev):
        if obj is self._stack and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self._stack.rect())
        return False

    # ── state ────────────────────────────────────────────────────────────────
    def state(self) -> tuple[str, QColor]:
        h = self._hud
        if h.muted:
            return "MUTED", qcol(C.MUTED_C)
        if h.speaking:
            return "SPEAKING", qcol(C.PRI)
        st = getattr(h, "state", "")
        if st in ("THINKING", "PROCESSING"):
            return st, qcol(C.WARN)
        if st == "LISTENING":
            return "LISTENING", qcol(C.LIVE)
        if st == "OFFLINE":
            return "OFFLINE", qcol(C.RED)
        if st == "SLEEPING":
            return "STANDBY", qcol(C.TEXT_DIM)
        return (st or "…")[:12], qcol(C.PRI_DIM)

    def card_rect(self) -> QRectF:
        return QRectF(self.width() - CARD_W - MARGIN_X, self.height() - CARD_H - MARGIN_Y,
                      CARD_W, CARD_H)

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        h = self._hud
        if self._sphere is not None:
            self._sphere.step(dt, float(getattr(h, "_amp_disp", 0.0)), h.state,
                              h.speaking, h.muted)
        speaking = bool(h.speaking) and not h.muted
        region = QRegion(self.card_rect().toAlignedRect().adjusted(-4, -4, 4, 4))
        if speaking or self._was_speaking:            # edge on, or fading out
            W, H = self.width(), self.height()
            for rr in ((0, 0, W, EDGE + 2), (0, H - EDGE - 2, W, EDGE + 2),
                       (0, 0, EDGE + 2, H), (W - EDGE - 2, 0, EDGE + 2, H)):
                region = region.united(QRegion(*rr))
        self._was_speaking = speaking
        self.update(region)

    # ── paint ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        label, col = self.state()
        h = self._hud
        amp = max(0.0, min(1.0, float(getattr(h, "_amp_disp", 0.0))))

        if h.speaking and not h.muted:
            edge = QColor(qcol(C.PRI))
            for i, a in enumerate((150, 70, 28)):
                edge.setAlpha(int(a * (0.55 + 0.45 * amp)))
                p.setPen(QPen(edge, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(0.5 + i, 0.5 + i, self.width() - 1 - 2 * i,
                                  self.height() - 1 - 2 * i))

        r = self.card_rect()
        bg = qcol(C.BG); bg.setAlpha(215)
        border = QColor(col); border.setAlpha(140)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)

        cx, cy = r.center().x(), r.top() + 12 + SPHERE_R * 1.25
        if self._sphere is not None:
            main, acc = h._state_colours() if hasattr(h, "_state_colours") else (col, col)
            p.save()
            p.setClipRect(r.adjusted(1, 1, -1, -1))
            self._sphere.paint(p, cx, cy, SPHERE_R, main, acc, qcol(C.BG))
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))

        f = QFont(FONT_UI, 9, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(QPen(col, 1))
        p.drawText(QRectF(r.left(), r.bottom() - 26, r.width(), 18),
                   Qt.AlignmentFlag.AlignCenter, label)
        p.end()
