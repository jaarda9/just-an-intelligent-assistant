"""
Keeps JARVIS visible while the browser, a video or the camera has the centre
of the HUD: a small live orb with his state in the bottom-right corner, and a
thin glowing edge around the page while he speaks.

It floats over the centre stack as a plain child (not a stack page), ignores
the mouse entirely, and only repaints while one of those pages is showing.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRegion
from PyQt6.QtWidgets import QWidget

from .base import C, FONT_UI, qcol

PILL_W, PILL_H, MARGIN = 132, 26, 12
EDGE = 3                      # px of glow around the page while speaking


class PresenceOverlay(QWidget):
    def __init__(self, stack, hud):
        super().__init__(stack)
        self._stack, self._hud = stack, hud
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._t = 0.0
        self._was_speaking = False
        self._tmr = QTimer(self)
        self._tmr.setInterval(50)                 # 20 Hz is plenty for a pulse
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

    def _pill_rect(self) -> QRectF:
        return QRectF(self.width() - PILL_W - MARGIN, self.height() - PILL_H - MARGIN,
                      PILL_W, PILL_H)

    def _tick(self) -> None:
        self._t += 0.05
        speaking = bool(self._hud.speaking) and not self._hud.muted
        r = self._pill_rect().toAlignedRect().adjusted(-4, -4, 4, 4)
        region = QRegion(r)
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
        amp = max(0.0, min(1.0, float(getattr(self._hud, "_amp_disp", 0.0))))

        if self._hud.speaking and not self._hud.muted:
            edge = QColor(qcol(C.PRI))
            for i, a in enumerate((150, 70, 28)):
                edge.setAlpha(int(a * (0.55 + 0.45 * amp)))
                p.setPen(QPen(edge, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(0.5 + i, 0.5 + i, self.width() - 1 - 2 * i,
                                  self.height() - 1 - 2 * i))

        r = self._pill_rect()
        bg = qcol(C.BG); bg.setAlpha(225)
        border = QColor(col); border.setAlpha(150)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, PILL_H / 2, PILL_H / 2)

        # orb: steady core, halo that breathes (and swells with the voice)
        ox, oy = r.left() + PILL_H / 2, r.center().y()
        pulse = 0.5 + 0.5 * math.sin(self._t * 3.2)
        halo = QColor(col); halo.setAlpha(int(50 + 60 * pulse))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        hr = 6.0 + 2.0 * pulse + 4.0 * amp
        p.drawEllipse(QRectF(ox - hr, oy - hr, hr * 2, hr * 2))
        p.setBrush(col)
        p.drawEllipse(QRectF(ox - 3.6, oy - 3.6, 7.2, 7.2))

        f = QFont(FONT_UI, 9, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(QPen(col, 1))
        p.drawText(QRectF(ox + 12, r.top(), r.right() - ox - 18, r.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        p.end()
