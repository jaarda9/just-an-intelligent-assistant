"""Now Playing panel — title, artist and app of the current media session,
with previous / play-pause / next. Hidden while nothing is playing."""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from .base import C, FONT_MONO, FONT_UI
from .chrome import GlassPanel


class NowPlayingPanel(GlassPanel):
    def __init__(self, parent=None):
        super().__init__("Now playing", parent, accent=C.GREEN)
        self._track = QLabel("")
        self._track.setFont(QFont(FONT_UI, 10, QFont.Weight.Bold))
        self._track.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        self._meta = QLabel("")
        self._meta.setFont(QFont(FONT_MONO, 8))
        self._meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self.body.addWidget(self._track)
        self.body.addWidget(self._meta)

        row = QHBoxLayout(); row.setSpacing(4)
        self._btns = {}
        for action, glyph in (("previous", "◀◀"), ("play_pause", "❚❚"), ("next", "▶▶")):
            b = QPushButton(glyph)
            b.setFixedHeight(26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont(FONT_UI, 9, QFont.Weight.Bold))
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_MED};
                    border: 1px solid {C.BORDER_A}; border-radius: 3px; }}
                QPushButton:hover {{ color: {C.GREEN}; border-color: {C.GREEN}; }}""")
            b.clicked.connect(lambda _=False, a=action: self._do(a))
            self._btns[action] = b
            row.addWidget(b)
        self.body.addLayout(row)
        self.hide()

    def show_info(self, info: dict | None) -> None:
        if not info or not info.get("title"):
            self.hide()
            return
        w = max(60, self.width() - 24)
        fm = self._track.fontMetrics()
        self._track.setText(fm.elidedText(info["title"], Qt.TextElideMode.ElideRight, w))
        sub = " · ".join(x for x in (info.get("artist"), info.get("app")) if x)
        self._meta.setText(self._meta.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, w))
        self._btns["play_pause"].setText("❚❚" if info.get("state") == "playing" else "▶")
        self.set_title("Now playing" if info.get("state") == "playing" else "Paused")
        self.show()

    def _do(self, action: str) -> None:
        from core import media
        threading.Thread(target=media.control, args=(action,), daemon=True,
                         name=f"media-{action}").start()
