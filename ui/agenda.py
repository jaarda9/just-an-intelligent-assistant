"""AGENDA panel — the next few calendar events (Google, read-only).
Hidden until Google is connected; shows nothing personal in guest mode."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel

from .base import C, FONT_MONO, FONT_UI
from .chrome import GlassPanel

MAX_ROWS = 3


class AgendaPanel(GlassPanel):
    def __init__(self, parent=None):
        super().__init__("Agenda", parent, accent=C.PRI)
        self._rows: list[tuple[QLabel, QLabel]] = []
        for _ in range(MAX_ROWS):
            when = QLabel(""); when.setFont(QFont(FONT_MONO, 8))
            when.setStyleSheet(f"color: {C.PRI}; background: transparent;")
            what = QLabel(""); what.setFont(QFont(FONT_UI, 9, QFont.Weight.DemiBold))
            what.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
            self.body.addWidget(when); self.body.addWidget(what)
            self._rows.append((when, what))
        self._note = QLabel("")
        self._note.setFont(QFont(FONT_UI, 8))
        self._note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self.body.addWidget(self._note)
        self.hide()

    def show_events(self, payload) -> None:
        """payload: None (not connected → hidden), 'guest', or a list of events."""
        if payload is None:
            self.hide()
            return
        for when, what in self._rows:
            when.hide(); what.hide()
        if payload == "guest":
            self._note.setText("Hidden while a guest is at the desk.")
            self._note.show(); self.show()
            return
        events = payload[:MAX_ROWS]
        if not events:
            self._note.setText("Nothing else today.")
            self._note.show(); self.show()
            return
        self._note.hide()
        today = dt.datetime.now().astimezone().date()
        w = max(60, self.width() - 24)
        for (when, what), e in zip(self._rows, events):
            start = e["start"].astimezone()
            day = "" if start.date() == today else start.strftime("%a ")
            when.setText("ALL DAY" if e["all_day"] else f"{day}{start:%H:%M}")
            what.setText(what.fontMetrics().elidedText(e["summary"], Qt.TextElideMode.ElideRight, w))
            when.show(); what.show()
        self.show()
