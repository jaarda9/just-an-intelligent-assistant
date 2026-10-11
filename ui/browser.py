"""
HUD browser — web pages open inside JARVIS's own interface, in tabs, taking
the centre of the HUD the way videos do, instead of a separate browser window.

Qt WebEngine (Chromium) with a persistent profile in config/browser_profile
(git-ignored): logins and cookies survive restarts like a normal browser.
Links that would open a new window open a new tab. Everything public here is
called on the Qt thread; JarvisUI marshals calls from worker threads.
"""
from __future__ import annotations

import re
import urllib.parse

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEBENGINE = True
except Exception:                                  # optional dependency
    HAVE_WEBENGINE = False

from .base import BASE_DIR, C, FONT_MONO, FONT_UI

PROFILE_DIR = BASE_DIR / "config" / "browser_profile"
_ICONS = (BASE_DIR / "assets" / "icons").as_posix()       # Qt stylesheets want forward slashes
SEARCH_URL = "https://www.google.com/search?q="
MAX_TABS = 12
_URLISH = re.compile(r"^(https?://|file://)|^[\w-]+(\.[\w-]+)+(:\d+)?(/.*)?$|^localhost(:\d+)?", re.I)


def to_url(text: str) -> str:
    """'stark.com' → https://stark.com; 'iron man suits' → a web search."""
    t = (text or "").strip()
    if not t:
        return "about:blank"
    if _URLISH.match(t) and " " not in t:
        return t if re.match(r"^[a-z]+://", t, re.I) else "https://" + t
    return SEARCH_URL + urllib.parse.quote_plus(t)


if HAVE_WEBENGINE:
    class _Page(QWebEnginePage):
        """Pages that ask for a new window get a new HUD tab instead."""

        def __init__(self, profile, browser: "HudBrowser"):
            super().__init__(profile, browser)
            self._browser = browser

        def createWindow(self, _type):
            view = self._browser.new_tab("about:blank", activate=True)
            return view.page()


class HudBrowser(QWidget):
    closed = pyqtSignal()                 # user pressed CLOSE — give the HUD back

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {C.BG};")
        self._views: list = []
        self._profile = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        # tab strip + close
        top = QHBoxLayout(); top.setSpacing(6)
        self._tabs = QTabBar()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setExpanding(False)
        self._tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self._tabs.setFont(QFont(FONT_UI, 9, QFont.Weight.DemiBold))
        self._tabs.setStyleSheet(f"""
            QTabBar::tab {{ background: transparent; color: {C.TEXT_DIM}; padding: 5px 12px;
                max-width: 190px; border: 1px solid {C.BORDER}; border-bottom: none;
                border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }}
            QTabBar::tab:selected {{ color: {C.WHITE}; background: {C.PANEL2}; border-color: {C.PRI_DIM}; }}
            QTabBar::tab:hover {{ color: {C.TEXT}; }}
            QTabBar::close-button {{ image: url("{_ICONS}/tab_close.svg"); subcontrol-position: right;
                margin-left: 4px; }}
            QTabBar::close-button:hover {{ image: url("{_ICONS}/tab_close_hover.svg"); }}""")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(self.close_tab)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        top.addWidget(self._tabs, stretch=1)
        self._b_new = self._btn("+", "New tab")
        self._b_new.clicked.connect(lambda: self.new_tab("about:blank") and self._url.setFocus())
        top.addWidget(self._b_new)
        b_close = self._btn("✕  CLOSE", "Back to the HUD")
        b_close.clicked.connect(self.closed.emit)
        top.addWidget(b_close)
        lay.addLayout(top)

        # navigation
        nav = QHBoxLayout(); nav.setSpacing(4)
        self._b_back = self._btn("◀", "Back")
        self._b_fwd = self._btn("▶", "Forward")
        self._b_reload = self._btn("⟳", "Reload")
        for b, fn in ((self._b_back, lambda: self._call("back")),
                      (self._b_fwd, lambda: self._call("forward")),
                      (self._b_reload, lambda: self._call("reload"))):
            b.clicked.connect(fn)
            nav.addWidget(b)
        self._url = QLineEdit()
        self._url.setPlaceholderText("Search or type an address")
        self._url.setFont(QFont(FONT_MONO, 9))
        self._url.setFixedHeight(28)
        self._url.setStyleSheet(f"""
            QLineEdit {{ background: {C.PANEL}; color: {C.WHITE}; border: 1px solid {C.BORDER_A};
                border-radius: 4px; padding: 2px 10px; }}
            QLineEdit:focus {{ border-color: {C.PRI}; }}""")
        self._url.returnPressed.connect(lambda: self.navigate(self._url.text()))
        nav.addWidget(self._url, stretch=1)
        lay.addLayout(nav)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"border: 1px solid {C.BORDER_A};")
        lay.addWidget(self._stack, stretch=1)

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def _btn(self, text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFixedHeight(28)
        b.setMinimumWidth(30)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFont(QFont(FONT_UI, 9, QFont.Weight.Bold))
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER_A};
                border-radius: 4px; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI}; }}""")
        return b

    # ── engine ───────────────────────────────────────────────────────────────
    def _ensure_profile(self):
        if self._profile is None:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._profile = QWebEngineProfile("jarvis", self)
            self._profile.setPersistentStoragePath(str(PROFILE_DIR / "storage"))
            self._profile.setCachePath(str(PROFILE_DIR / "cache"))
        return self._profile

    def _current(self):
        i = self._tabs.currentIndex()
        return self._views[i] if 0 <= i < len(self._views) else None

    def _call(self, method: str) -> None:
        v = self._current()
        if v is not None:
            getattr(v, method)()

    # ── public API (Qt thread) ───────────────────────────────────────────────
    def new_tab(self, target: str = "about:blank", activate: bool = True):
        if not HAVE_WEBENGINE:
            return None
        if len(self._views) >= MAX_TABS:
            self.close_tab(0)                         # recycle the oldest
        view = QWebEngineView()
        view.setPage(_Page(self._ensure_profile(), self))
        view.titleChanged.connect(lambda t, v=view: self._retitle(v, t))
        view.urlChanged.connect(lambda u, v=view: self._on_url(v, u))
        self._views.append(view)
        self._stack.addWidget(view)
        idx = self._tabs.addTab("New tab")
        if target and target != "about:blank":
            view.setUrl(QUrl(to_url(target)))
        if activate:
            self._tabs.setCurrentIndex(idx)
        return view

    def navigate(self, text: str) -> None:
        v = self._current() or self.new_tab()
        if v is not None:
            v.setUrl(QUrl(to_url(text)))
            v.setFocus()

    def open(self, text: str, new_tab: bool = True) -> int:
        """Open a URL or search; returns the tab index."""
        if new_tab or not self._views:
            self.new_tab(text)
        else:
            self.navigate(text)
        return self._tabs.currentIndex()

    def close_tab(self, index: int | None = None) -> None:
        i = self._tabs.currentIndex() if index is None else index
        if not (0 <= i < len(self._views)):
            return
        view = self._views.pop(i)
        self._tabs.removeTab(i)
        self._stack.removeWidget(view)
        view.deleteLater()
        if not self._views:
            self.closed.emit()                         # last tab gone → back to the HUD

    def switch(self, index: int) -> bool:
        if 0 <= index < len(self._views):
            self._tabs.setCurrentIndex(index)
            return True
        return False

    def tabs(self) -> list[dict]:
        cur = self._tabs.currentIndex()
        return [{"index": i, "title": v.title() or "New tab", "url": v.url().toString(),
                 "active": i == cur} for i, v in enumerate(self._views)]

    def read_current(self, callback) -> None:
        """callback(title, url, text) with the visible page's text."""
        v = self._current()
        if v is None:
            callback("", "", "")
            return
        v.page().toPlainText(lambda text, v=v: callback(v.title(), v.url().toString(), text or ""))

    def has_tabs(self) -> bool:
        return bool(self._views)

    def shutdown(self) -> None:
        """Destroy pages, then views, then the profile — in that order, now.
        Chromium requires every page to be gone before its profile; left to
        interpreter teardown the order is arbitrary and the process crashes
        on exit (0xC0000005). Runs on QApplication.aboutToQuit."""
        from PyQt6 import sip
        for v in self._views:
            try:
                page = v.page()
                if page is not None and not sip.isdeleted(page):
                    sip.delete(page)
                if not sip.isdeleted(v):
                    sip.delete(v)
            except Exception:
                pass
        self._views.clear()
        if self._profile is not None and not sip.isdeleted(self._profile):
            try:
                sip.delete(self._profile)
            except Exception:
                pass
        self._profile = None

    # ── internals ────────────────────────────────────────────────────────────
    def _retitle(self, view, title: str) -> None:
        if view in self._views:
            i = self._views.index(view)
            self._tabs.setTabText(i, title or "New tab")
            self._tabs.setTabToolTip(i, title or "")

    def _on_url(self, view, url: QUrl) -> None:
        if view is self._current():
            self._url.setText(url.toString() if url.toString() != "about:blank" else "")
        self._sync_nav()

    def _on_tab_changed(self, i: int) -> None:
        if 0 <= i < len(self._views):
            self._stack.setCurrentWidget(self._views[i])
            u = self._views[i].url().toString()
            self._url.setText("" if u == "about:blank" else u)
        self._sync_nav()

    def _on_tab_moved(self, frm: int, to: int) -> None:
        self._views.insert(to, self._views.pop(frm))

    def _sync_nav(self) -> None:
        v = self._current()
        h = v.history() if v is not None else None
        self._b_back.setEnabled(bool(h and h.canGoBack()))
        self._b_fwd.setEnabled(bool(h and h.canGoForward()))
