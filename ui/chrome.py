"""
Interface chrome for the Mark III look: glass panels with corner brackets,
live status chips, glow, and the frameless window's controls.

Everything paints from the theme palette (C) at paint time, so live
re-theming from the hue wheel reaches these widgets on their next repaint.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QBrush
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .base import C, FONT_HEAD, FONT_MONO, FONT_UI, qcol


def glow(widget: QWidget, color: str | None = None, radius: int = 18, alpha: int = 170) -> None:
    """Soft light around a widget's content (text reads as lit, not printed)."""
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color or C.PRI)
    c.setAlpha(alpha)
    eff.setColor(c)
    eff.setBlurRadius(radius)
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)


def _mix(a: str, b: str, k: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * k),
                  int(ca.green() + (cb.green() - ca.green()) * k),
                  int(ca.blue() + (cb.blue() - ca.blue()) * k))


class GlassPanel(QFrame):
    """A HUD panel: faint vertical gradient, hairline border, bright corner
    brackets and an optional Orbitron title with an accent tick. Put content
    in .body (a QVBoxLayout)."""

    TITLE_H = 22

    def __init__(self, title: str = "", parent=None, accent: str | None = None):
        super().__init__(parent)
        self._title = title.upper()
        self._accent = accent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.body = QVBoxLayout(self)
        top = self.TITLE_H + 6 if title else 10
        self.body.setContentsMargins(10, top, 10, 10)
        self.body.setSpacing(6)

    def set_title(self, title: str) -> None:
        self._title = title.upper()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        acc = qcol(self._accent or C.PRI)
        r = QRectF(0.5, 0.5, W - 1, H - 1)

        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0.0, _mix(C.BG, C.PRI, 0.045))
        g.setColorAt(1.0, _mix(C.BG, C.PRI, 0.012))
        p.setBrush(QBrush(g))
        p.setPen(QPen(_mix(C.BG, C.PRI, 0.16), 1))
        p.drawRect(r)

        # corner brackets — what makes a box read as a HUD element
        arm = min(14.0, W * 0.12, H * 0.2)
        p.setPen(QPen(_mix(C.BG, acc.name(), 0.75), 1.6))
        for x, y, sx, sy in ((0.5, 0.5, 1, 1), (W - 0.5, 0.5, -1, 1),
                             (0.5, H - 0.5, 1, -1), (W - 0.5, H - 0.5, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + sx * arm, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + sy * arm))

        if self._title:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc)
            p.drawRect(QRectF(10, 9, 3, 9))
            f = QFont(FONT_HEAD, 8, QFont.Weight.DemiBold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
            p.setFont(f)
            p.setPen(QPen(_mix(C.BG, acc.name(), 0.9), 1))
            p.drawText(QRectF(19, 4, W - 30, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)
            p.setPen(QPen(_mix(C.BG, C.PRI, 0.14), 1))
            p.drawLine(QPointF(10, self.TITLE_H + 1), QPointF(W - 10, self.TITLE_H + 1))
        p.end()


class StatusChip(QWidget):
    """One live status line: a pulsing dot, a label and a value.
    level: 'ok' | 'warn' | 'alert' | 'off'."""

    _COLOURS = {"ok": "GREEN", "warn": "ACC2", "alert": "RED", "off": "TEXT_DIM", "info": "PRI"}

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label.upper()
        self._value = "—"
        self._level = "off"
        self.setFixedHeight(30)
        self.setMinimumWidth(100)

    def set(self, level: str, value: str) -> None:
        if (level, value) != (self._level, self._value):
            self._level, self._value = level, value
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        col = qcol(getattr(C, self._COLOURS.get(self._level, "TEXT_DIM")))

        p.setPen(QPen(_mix(C.BG, C.PRI, 0.13), 1))
        p.setBrush(_mix(C.BG, C.PRI, 0.03))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 3, 3)
        # status bar on the left edge, in the status colour
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0.5, 4, 2.5, H - 8), 1, 1)

        halo = QColor(col); halo.setAlpha(60)
        p.setBrush(halo)
        p.drawEllipse(QPointF(13, H / 2), 5, 5)
        p.setBrush(col)
        p.drawEllipse(QPointF(13, H / 2), 2.6, 2.6)

        f = QFont(FONT_UI, 8, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(f)
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(24, 0, W - 28, H / 2 + 2),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self._label)
        p.setFont(QFont(FONT_MONO, 8))
        p.setPen(QPen(col, 1))
        p.drawText(QRectF(24, H / 2 - 1, W - 28, H / 2),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self._value)
        p.end()


class IconButton(QPushButton):
    """Checkable header button with a vector icon ('gear' or 'sliders') —
    emoji glyphs render in full colour and break the HUD palette."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        on, hot = self.isChecked(), self.underMouse()
        frame = qcol(C.PRI if on else (C.PRI_DIM if hot else C.BORDER_A))
        p.setPen(QPen(frame, 1))
        fill = qcol(C.PRI); fill.setAlpha(38 if on else (18 if hot else 0))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 4, 4)
        col = qcol(C.PRI if (on or hot) else C.TEXT_MED)
        p.setPen(QPen(col, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = W / 2, H / 2
        if self._kind == "gear":
            p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
            for k in range(8):
                a = math.radians(k * 45)
                p.drawLine(QPointF(cx + math.cos(a) * 6.0, cy + math.sin(a) * 6.0),
                           QPointF(cx + math.cos(a) * 8.6, cy + math.sin(a) * 8.6))
            p.drawEllipse(QPointF(cx, cy), 6.0, 6.0)
        else:                                       # sliders
            for i, knob in enumerate((-3.5, 3.0, -1.0)):
                x = cx - 6 + i * 6
                p.drawLine(QPointF(x, cy - 8), QPointF(x, cy + 8))
                p.setBrush(col)
                p.drawRoundedRect(QRectF(x - 2.4, cy + knob - 1.6, 4.8, 3.2), 1, 1)
                p.setBrush(Qt.BrushStyle.NoBrush)
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class WindowButton(QPushButton):
    """Minimise / maximise / close for the frameless window, drawn as thin
    vector glyphs so they match the HUD rather than the OS."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(34, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip({"min": "Minimise", "max": "Maximise / restore",
                         "close": "Close"}[kind])
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        hot = self.underMouse()
        if hot:
            bg = qcol(C.RED if self._kind == "close" else C.PRI)
            bg.setAlpha(70 if self._kind == "close" else 40)
            p.fillRect(self.rect(), bg)
        col = qcol(C.WHITE if hot else C.TEXT_MED)
        p.setPen(QPen(col, 1.3))
        cx, cy, s = W / 2, H / 2, 5
        if self._kind == "min":
            p.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        elif self._kind == "max":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(cx - s, cy - s + 1, s * 2, s * 2 - 2))
        else:
            p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            p.drawLine(QPointF(cx + s, cy - s), QPointF(cx - s, cy + s))
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)
