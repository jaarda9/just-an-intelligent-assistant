"""Window chrome: frameless move/resize, fullscreen, boot, mini-mode, notifications.

Mixed into ui.window.MainWindow; methods use its widgets via self."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from .base import _read_full_config
from .chrome import GlassPanel

class ChromeMixin:
    # ── access points: tray, summon hotkey, close behaviour ──────────────────
    def _setup_access_points(self):
        from PyQt6.QtGui import QKeySequence, QShortcut
        from core.summon import GlobalHotkey, DEFAULT_LABEL
        app = QApplication.instance()
        # With a tray and a mini orb, "last window closed" no longer means
        # "quit" — quitting is explicit (closeEvent / tray menu).
        app.setQuitOnLastWindowClosed(False)
        self._tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            from .tray import JarvisTray
            self._tray = JarvisTray(self)
            self._tray.show()
        self._summon_sig.connect(self.summon)
        self._summon_key = GlobalHotkey(self._summon_sig.emit)
        scope = self._summon_key.start()
        if scope != "global":
            # Not global (other OS, or the chord is taken): at least bind it
            # while the window has focus.
            QShortcut(QKeySequence(DEFAULT_LABEL), self).activated.connect(self.summon)
        self._summon_scope = scope
        print(f"[Summon] {DEFAULT_LABEL}: {scope}")

    def summon(self):
        """Bring JARVIS to the front from wherever it is: minimised, hidden to
        the tray, or shrunk to the mini orb. Pressing it while JARVIS is
        already in front sends it to mini-mode — one key toggles."""
        mini = getattr(self, "_mini", None)
        if mini is not None and mini.isVisible():
            self.exit_mini()
            return
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.enter_mini()
            return
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if _read_full_config().get("close_to_tray", False) and getattr(self, "_tray", None):
            e.ignore()
            self.hide()
            self._tray.showMessage(self._assistant_name.upper(),
                                   "Still running in the tray. Ctrl+Alt+J brings me back.",
                                   QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        try:
            self._summon_key.stop()
            from core import media
            media.unwatch(self._media_cb)
        except Exception:
            pass
        if getattr(self, "_tray", None) is not None:
            self._tray.hide()
        super().closeEvent(e)
        QApplication.instance().quit()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ── frameless window: move, resize, maximise ─────────────────────────────
    _EDGE = 5

    def _apply_frameless(self) -> None:
        """Drop the OS title bar ("frameless": false in config restores it).
        Moving and resizing go through the OS (startSystemMove/Resize), so
        Windows snapping and multi-monitor behaviour keep working."""
        if not _read_full_config().get("frameless", True):
            self._frameless = False
            return
        self._frameless = True
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

    _GRIPS = (  # (edges, cursor)
        (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
        (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
        (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
        (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
        (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
        (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor),
        (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
        (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
    )

    def _install_grips(self) -> None:
        """Eight invisible resize strips on the frameless window's border."""
        from .chrome import ResizeGrip
        self._grips = [ResizeGrip(self, e, c) for e, c in self._GRIPS]
        self._place_grips()

    def _place_grips(self) -> None:
        grips = getattr(self, "_grips", None)
        if not grips:
            return
        show = getattr(self, "_frameless", False) and not (self.isMaximized() or self.isFullScreen())
        W, H, e, k = self.width(), self.height(), self._EDGE, self._EDGE * 2
        rects = (
            (0, k, e, H - 2 * k), (W - e, k, e, H - 2 * k),          # left, right
            (k, 0, W - 2 * k, e), (k, H - e, W - 2 * k, e),          # top, bottom
            (0, 0, k, k), (W - k, H - k, k, k),                      # TL, BR
            (W - k, 0, k, k), (0, H - k, k, k),                      # TR, BL
        )
        for g, r in zip(grips, rects):
            g.setGeometry(*r)
            g.setVisible(show)
            g.raise_()

    def _toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # ── boot ─────────────────────────────────────────────────────────────────
    def _start_boot(self):
        """HUD boot sequence plus the glass panels fading in one by one."""
        self.hud._start_boot()
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        panels = (self._left_panel.findChildren(GlassPanel)
                  + self._right_panel.findChildren(GlassPanel))
        self._boot_anims = []
        for i, panel in enumerate(panels):
            fx = QGraphicsOpacityEffect(panel)
            fx.setOpacity(0.0)
            panel.setGraphicsEffect(fx)
            a = QPropertyAnimation(fx, b"opacity", self)
            a.setDuration(450)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Opacity effects re-render their widget offscreen every frame;
            # drop each one as soon as its panel is fully in.
            a.finished.connect(lambda p=panel: p.setGraphicsEffect(None))
            QTimer.singleShot(400 + i * 180, a.start)
            self._boot_anims.append(a)

    # ── mini-mode ────────────────────────────────────────────────────────────
    def enter_mini(self):
        if getattr(self, "_mini", None) is None:
            from .mini import MiniOrb
            self._mini = MiniOrb(self)
        self._mini.open()
        self.hide()

    def exit_mini(self):
        if getattr(self, "_mini", None) is not None:
            self._mini.close_orb()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_mini(self):
        if getattr(self, "_mini", None) is not None and self._mini.isVisible():
            self.exit_mini()
        else:
            self.enter_mini()

    def _show_toast(self, title: str, text: str, level: str) -> None:
        self._toasts.show(title, text, level)
        if getattr(self, "_mini", None) is not None and self._mini.isVisible():
            self._mini.notify(title, text, level)
