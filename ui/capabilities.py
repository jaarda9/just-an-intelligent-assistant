"""
"What can you do?" — a panel generated from the running app: every tool the
assistant can call right now, grouped, plus the keys and access points.
Generated, not written, so it can never drift from what the build does.
"""
from __future__ import annotations

import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .base import C, FONT_HEAD, FONT_UI

# Tool name → group. Anything unlisted lands in "More".
GROUPS = [
    ("Computer", ["open_app", "computer_settings", "computer_control", "desktop_control",
                  "file_controller", "file_processor", "system_status", "run_diagnostics"]),
    ("Web & media", ["web_search", "browser_control", "youtube_video", "video_player",
                     "media_control", "weather_report", "flight_finder"]),
    ("Routines", ["run_protocol", "reminder"]),
    ("Accounts & messages", ["google_services", "send_message"]),
    ("Security", ["security_report", "presence", "access_control"]),
    ("Code", ["code_helper", "dev_agent", "game_updater"]),
]
KEYS = [("Ctrl+Alt+J", "summon from any app"), ("Ctrl+Space", "push-to-talk (hold)"),
        ("F4", "mute"), ("F9", "mini-mode"), ("F11", "fullscreen"), ("Esc", "interrupt")]


def build_html(catalog: list[dict]) -> str:
    by_name = {t["name"]: t for t in catalog}
    placed: set[str] = set()
    parts = []

    def section(title: str, names: list[str]) -> None:
        rows = []
        for n in names:
            t = by_name.get(n)
            if not t:
                continue
            placed.add(n)
            desc = (t.get("description") or "").split(". ")[0].strip()
            if len(desc) > 110:                      # cut at a word, not mid-word
                desc = desc[:110].rsplit(" ", 1)[0].rstrip(",;:") + "…"
            desc = html.escape(desc)
            rows.append(f"<tr><td style='color:{C.PRI};padding:2px 14px 2px 0;white-space:nowrap'>"
                        f"{html.escape(n)}</td><td style='color:{C.TEXT}'>{desc}</td></tr>")
        if rows:
            parts.append(f"<p style='color:{C.ACC2};font-weight:700;letter-spacing:2px;"
                         f"margin:10px 0 4px'>{html.escape(title.upper())}</p>"
                         f"<table cellspacing='0'>{''.join(rows)}</table>")

    for title, names in GROUPS:
        section(title, names)
    section("More", sorted(n for n in by_name if n not in placed))
    keys = "".join(f"<tr><td style='color:{C.GREEN};padding:2px 14px 2px 0'>{k}</td>"
                   f"<td style='color:{C.TEXT}'>{v}</td></tr>" for k, v in KEYS)
    parts.append(f"<p style='color:{C.ACC2};font-weight:700;letter-spacing:2px;margin:12px 0 4px'>"
                 f"KEYS</p><table cellspacing='0'>{keys}</table>")
    parts.append(f"<p style='color:{C.TEXT_DIM};margin-top:12px'>Also: tray icon, "
                 f"<span style='color:{C.PRI}'>jarvis \"…\"</span> in a terminal, and the phone "
                 f"dashboard (⚙ → Remote Control). Full guide: docs/JARVIS.md.</p>")
    return "".join(parts)


class CapabilitiesOverlay(QWidget):
    _OW, _OH = 620, 520

    def __init__(self, catalog: list[dict], parent=None):
        super().__init__(parent)
        self.setFixedSize(self._OW, self._OH)
        self.setObjectName("Caps")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#Caps {{ background: rgba(0,6,10,248); "
                           f"border: 1px solid {C.BORDER_B}; border-radius: 6px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        title = QLabel("WHAT CAN YOU DO?")
        tf = QFont(FONT_HEAD, 11, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        title.setFont(tf)
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(title)
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setFont(QFont(FONT_UI, 10))
        view.setStyleSheet(f"""
            QTextBrowser {{ background: transparent; border: none; color: {C.TEXT}; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_A}; border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}""")
        view.setHtml(build_html(catalog))
        lay.addWidget(view, stretch=1)
        self._view = view
        row = QHBoxLayout(); row.addStretch()
        close = QPushButton("CLOSE")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedHeight(28)
        close.setStyleSheet(f"QPushButton {{ background: transparent; color: {C.TEXT_MED}; "
                            f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 0 14px; }}"
                            f"QPushButton:hover {{ border-color: {C.PRI}; }}")
        close.clicked.connect(lambda: (self.hide(), self.deleteLater()))
        row.addWidget(close)
        lay.addLayout(row)
