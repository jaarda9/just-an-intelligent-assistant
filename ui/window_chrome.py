"""Window chrome: frameless move/resize, fullscreen, boot, mini-mode, notifications.

Mixed into ui.window.MainWindow; methods use its widgets via self."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QTimer, Qt
from .base import _read_full_config
from .chrome import GlassPanel

class ChromeMixin:
    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ── frameless window: move, resize, maximise ─────────────────────────────
    _EDGE = 6

    def _apply_frameless(self) -> None:
        """Drop the OS title bar ("frameless": false in config restores it).
        Moving and resizing go through the OS (startSystemMove/Resize), so
        Windows snapping and multi-monitor behaviour keep working."""
        if not _read_full_config().get("frameless", True):
            self._frameless = False
            return
        self._frameless = True
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _edges_at(self, gpos) -> Qt.Edge:
        if not getattr(self, "_frameless", False) or self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        r, e, edges = self.frameGeometry(), self._EDGE, Qt.Edge(0)
        if gpos.x() <= r.left() + e:     edges |= Qt.Edge.LeftEdge
        if gpos.x() >= r.right() - e:    edges |= Qt.Edge.RightEdge
        if gpos.y() <= r.top() + e:      edges |= Qt.Edge.TopEdge
        if gpos.y() >= r.bottom() - e:   edges |= Qt.Edge.BottomEdge
        return edges

    _EDGE_CURSORS = {
        Qt.Edge.LeftEdge.value: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.RightEdge.value: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge.value: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.BottomEdge.value: Qt.CursorShape.SizeVerCursor,
        (Qt.Edge.LeftEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeFDiagCursor,
        (Qt.Edge.RightEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeFDiagCursor,
        (Qt.Edge.RightEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeBDiagCursor,
        (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeBDiagCursor,
    }

    def event(self, e):
        if getattr(self, "_frameless", False):
            t = e.type()
            if t == QEvent.Type.HoverMove:
                edges = self._edges_at(self.mapToGlobal(e.position().toPoint()))
                shape = self._EDGE_CURSORS.get(edges.value)
                if shape is not None:
                    self.setCursor(shape)
                else:
                    self.unsetCursor()
            elif t == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                edges = self._edges_at(e.globalPosition().toPoint())
                if edges != Qt.Edge(0) and self.windowHandle():
                    self.windowHandle().startSystemResize(edges)
                    return True
        return super().event(e)

    def eventFilter(self, obj, e):
        if obj is getattr(self, "_header", None):
            t = e.type()
            if t == QEvent.Type.MouseButtonDblClick and e.button() == Qt.MouseButton.LeftButton:
                if getattr(self, "_frameless", False):
                    self._toggle_maximized()
                    return True
            elif t == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                edges = self._edges_at(e.globalPosition().toPoint())
                if getattr(self, "_frameless", False) and self.windowHandle():
                    if edges != Qt.Edge(0):
                        self.windowHandle().startSystemResize(edges)
                    else:
                        self.windowHandle().startSystemMove()
                    return True
        return super().eventFilter(obj, e)

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
