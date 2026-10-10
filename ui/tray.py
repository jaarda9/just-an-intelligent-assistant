"""
System tray icon: JARVIS's presence when the window is out of the way.

The icon is drawn, not loaded: a ring in the current state colour (blue idle,
green listening, gold thinking, red muted), so the tray itself shows what
JARVIS is doing. The menu holds the everyday actions — show/hide, mini-mode,
mute, protocols (read live from config/protocols.json), presence — and the
one explicit Quit.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .base import C, FONT_UI, qcol


def _state_icon(colour: QColor) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = qcol(C.BG)
    p.setBrush(bg)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(32, 32), 30, 30)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour, 6))
    p.drawEllipse(QPointF(32, 32), 22, 22)
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(32, 32), 8, 8)
    p.end()
    return QIcon(pm)


class JarvisTray(QSystemTrayIcon):
    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self._last_key = None
        self.setToolTip(f"{window._assistant_name.upper()} — {window.windowTitle()}")
        self.activated.connect(self._on_activated)

        m = QMenu()
        m.setStyleSheet(f"""
            QMenu {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER_A};
                     font-family: {FONT_UI}; font-size: 10pt; padding: 4px; }}
            QMenu::item {{ padding: 5px 22px 5px 14px; }}
            QMenu::item:selected {{ background: {C.PRI_GHO}; color: {C.WHITE}; }}
            QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 4px 8px; }}
        """)
        self._a_show = m.addAction("Open HUD", self._show_hud)
        m.addAction("Mini-mode", window.enter_mini)
        m.addSeparator()
        self._a_mute = QAction("Mute microphone", m, checkable=True)
        self._a_mute.triggered.connect(lambda on: window._set_muted(on))
        m.addAction(self._a_mute)
        self._protocols = m.addMenu("Protocols")
        self._protocols.aboutToShow.connect(self._fill_protocols)
        m.addAction("Edit protocols…", lambda: (window.summon(), window._open_protocol_editor()))
        self._a_presence = QAction("Presence (webcam)", m, checkable=True)
        self._a_presence.triggered.connect(self._toggle_presence)
        m.addAction(self._a_presence)
        m.addSeparator()
        m.addAction("Quit", self._quit)
        m.aboutToShow.connect(self._sync_checks)
        self._menu = m
        self.setContextMenu(m)
        self.refresh()

    # ── live icon ────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        hud = self._win.hud
        key = (hud.state, hud.speaking, self._win._muted, C.PRI)
        if key == self._last_key:
            return
        self._last_key = key
        if self._win._muted:
            col = qcol(C.MUTED_C)
        else:
            _, col = hud._state_colours()
        self.setIcon(_state_icon(col))
        state = "muted" if self._win._muted else ("speaking" if hud.speaking else hud.state.lower())
        self.setToolTip(f"{self._win._assistant_name.upper()} — {state}")

    # ── actions ──────────────────────────────────────────────────────────────
    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._win.summon()

    def _show_hud(self) -> None:
        self._win.summon()

    def _sync_checks(self) -> None:
        self._a_mute.setChecked(self._win._muted)
        try:
            from core.presence import get_presence
            pr = get_presence()
            self._a_presence.setEnabled(pr.enrolled())
            self._a_presence.setChecked(pr.enabled())
            self._a_presence.setText("Presence (webcam)" if pr.enrolled()
                                     else "Presence — say \"learn my face\" first")
        except Exception:
            self._a_presence.setEnabled(False)

    def _toggle_presence(self, on: bool) -> None:
        try:
            from core.presence import get_presence
            msg = get_presence().set_enabled(on)
            self._win._log.append_log(f"SYS: {msg}")
        except Exception as e:
            self._win._log.append_log(f"ERR: presence — {e}")

    def _fill_protocols(self) -> None:
        self._protocols.clear()
        try:
            from plugins.protocols import _load
            names = list(_load())
        except Exception:
            names = []
        if not names:
            self._protocols.addAction("(none defined)").setEnabled(False)
            return
        for name in names:
            self._protocols.addAction(name.title(), lambda n=name: self._run_protocol(n))

    def _run_protocol(self, name: str) -> None:
        run = getattr(self._win, "run_tool", None)
        if not callable(run):
            self._win._log.append_log("SYS: Protocols need the assistant to be running.")
            return
        self._win._log.append_log(f"YOU: (tray) {name} protocol")
        threading.Thread(target=run, args=("run_protocol", {"name": name}),
                         daemon=True, name=f"protocol-{name}").start()

    def _quit(self) -> None:
        self.hide()
        QApplication.instance().quit()
