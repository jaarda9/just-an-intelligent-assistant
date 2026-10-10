"""
Mini-mode: JARVIS as a small always-on-top orb while you work elsewhere.

A frameless, translucent tool window with its own small Holo-Sphere, driven by
the main HUD's live state and audio level. Notifications appear as a bubble
beside the orb. Drag to move; click (without dragging) to bring the full HUD
back. While it is up the main window is hidden, so the big HUD stops painting.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .base import C, FONT_HEAD, FONT_MONO, FONT_UI, qcol

ORB = 132            # orb area (square)
BUBBLE_W = 250


class MiniOrb(QWidget):
    def __init__(self, main_window):
        super().__init__(None)
        self._main = main_window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("JARVIS mini")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to open the full HUD · drag to move")
        self.resize(ORB, ORB)
        self._sphere = None
        self._bubble: tuple[str, str, str, float] | None = None
        self._press: QPoint | None = None
        self._last = time.time()
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)

    # ── show / hide ──────────────────────────────────────────────────────────
    def open(self) -> None:
        if self._sphere is None:
            from core.holosphere import HoloSphere
            self._sphere = HoloSphere(n=520)          # fewer points: it is small
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.right() - ORB - 24, scr.bottom() - ORB - 24)
        self._last = time.time()
        self._tmr.start(33)
        self.show()
        self.raise_()

    def close_orb(self) -> None:
        self._tmr.stop()
        self.hide()

    # ── notifications ────────────────────────────────────────────────────────
    def notify(self, title: str, text: str, level: str = "info") -> None:
        if not self.isVisible():
            return
        self._bubble = (title.upper()[:32], text, level, time.time() + 6.0)
        self._set_bubble_geometry(True)

    def _set_bubble_geometry(self, with_bubble: bool) -> None:
        # Grow / shrink to the LEFT so the orb itself never moves.
        g = self.geometry()
        right = g.right()
        w = ORB + (BUBBLE_W if with_bubble else 0)
        self.setGeometry(QRect(right - w + 1, g.top(), w, ORB))

    # ── animation ────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        now = time.time()
        dt, self._last = now - self._last, now
        hud = self._main.hud
        if self._sphere is not None:
            self._sphere.step(dt, getattr(hud, "_amp_disp", 0.0), hud.state,
                              hud.speaking, hud.muted)
        if self._bubble and now > self._bubble[3]:
            self._bubble = None
            self._set_bubble_geometry(False)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W - ORB / 2, ORB / 2
        hud = self._main.hud
        main, acc = hud._state_colours()

        # backing disc so the orb reads on any wallpaper
        bg = qcol(C.BG); bg.setAlpha(215)
        p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), 110), 1.4))
        p.setBrush(bg)
        p.drawEllipse(QPointF(cx, cy), ORB / 2 - 3, ORB / 2 - 3)
        if self._sphere is not None:
            self._sphere.paint(p, cx, cy - 4, ORB * 0.27, main, acc, qcol(C.BG))

        f = QFont(FONT_UI, 7, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(QPen(acc, 1))
        p.drawText(QRectF(cx - ORB / 2, cy + ORB * 0.30, ORB, 14),
                   Qt.AlignmentFlag.AlignCenter,
                   "MUTED" if hud.muted else ("SPEAKING" if hud.speaking else hud.state))

        if self._bubble:
            title, text, level, _ = self._bubble
            col = qcol({"ok": C.GREEN, "warn": C.ACC2, "alert": C.RED}.get(level, C.PRI))
            r = QRectF(4, ORB / 2 - 32, BUBBLE_W - 14, 64)
            bb = qcol(C.BG); bb.setAlpha(235)
            p.setBrush(bb)
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 140), 1))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
            p.drawRoundedRect(QRectF(r.left(), r.top() + 7, 3, r.height() - 14), 1.5, 1.5)
            tf = QFont(FONT_HEAD, 7, QFont.Weight.DemiBold)
            tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.3)
            p.setFont(tf); p.setPen(QPen(col, 1))
            p.drawText(QRectF(r.left() + 12, r.top() + 6, r.width() - 18, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
            p.setFont(QFont(FONT_UI, 9, QFont.Weight.Medium)); p.setPen(QPen(qcol(C.WHITE), 1))
            p.drawText(QRectF(r.left() + 12, r.top() + 22, r.width() - 18, r.height() - 26),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                       | Qt.TextFlag.TextWordWrap, text)
        p.end()

    # ── interaction ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and \
                (e.globalPosition().toPoint() - self._press).manhattanLength() > 5:
            self._press = None
            if self.windowHandle():
                self.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        if self._press is not None and e.button() == Qt.MouseButton.LeftButton:
            self._press = None
            self._main.exit_mini()
