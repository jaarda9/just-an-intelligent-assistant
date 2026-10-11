"""TASKS panel — what JARVIS is working on, with elapsed time and progress.
Hidden when idle. Fed by core/tasks.py; repaints on change and once a
second while something is running (for the elapsed clocks)."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .base import C, FONT_MONO, FONT_UI, qcol
from .chrome import GlassPanel

ROW_H = 34


class _Rows(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self._tasks = []

    def set_tasks(self, tasks):
        self._tasks = tasks
        self.setFixedHeight(max(ROW_H, ROW_H * len(tasks)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self.width()
        for i, t in enumerate(self._tasks):
            y = i * ROW_H
            if t.finished is None:
                col = qcol(C.ACC2)
                mark = "◈"
            else:
                col = qcol(C.LIVE if t.ok else C.RED)
                mark = "✓" if t.ok else "✗"
            p.setFont(QFont(FONT_UI, 9, QFont.Weight.Bold))
            p.setPen(QPen(col, 1))
            p.drawText(QRectF(0, y, 16, 18), Qt.AlignmentFlag.AlignVCenter, mark)
            p.setPen(QPen(qcol(C.WHITE), 1))
            p.drawText(QRectF(16, y, W - 70, 18), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(t.name, Qt.TextElideMode.ElideRight, int(W - 90)))
            p.setFont(QFont(FONT_MONO, 8))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            secs = int(t.elapsed)
            p.drawText(QRectF(W - 54, y, 54, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{secs // 60}:{secs % 60:02d}")
            if t.detail:
                p.drawText(QRectF(16, y + 15, W - 16, 12), Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(t.detail, Qt.TextElideMode.ElideRight, int(W - 20)))
            # progress track: determinate bar, or a sweeping segment while unknown
            ty = y + ROW_H - 5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcol(C.BAR_BG))
            p.drawRoundedRect(QRectF(16, ty, W - 16, 2.5), 1, 1)
            p.setBrush(col)
            if t.progress is not None or t.finished is not None:
                frac = 1.0 if t.finished is not None else t.progress
                p.drawRoundedRect(QRectF(16, ty, (W - 16) * frac, 2.5), 1, 1)
            else:
                seg = (W - 16) * 0.3
                x = 16 + ((t.elapsed * 0.6) % 1.0) * (W - 16 - seg)
                p.drawRoundedRect(QRectF(x, ty, seg, 2.5), 1, 1)
        p.end()


class TaskPanel(GlassPanel):
    def __init__(self, board, parent=None):
        super().__init__("Tasks", parent, accent=C.ACC2)
        self._board = board
        self._rows = _Rows(self)
        self.body.addWidget(self._rows)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh)
        self.hide()

    def refresh(self) -> None:
        tasks = self._board.snapshot()
        if not tasks:
            self.hide()
            if self._board.active() == 0:
                self._tick.stop()
            return
        running = sum(1 for t in tasks if t.finished is None)
        self.set_title(f"Tasks · {running} running" if running else "Tasks")
        self._rows.set_tasks(tasks)
        self.show()
        if not self._tick.isActive():
            self._tick.start(250)          # smooth progress sweep + elapsed clocks

    def poke(self) -> None:
        """Called (via a signal) whenever the board changes; tasks only become
        visible after a short delay, so keep ticking until then."""
        if not self._tick.isActive():
            self._tick.start(250)
