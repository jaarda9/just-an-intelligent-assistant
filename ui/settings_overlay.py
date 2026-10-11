"""
System settings — one place for the switches that used to live only in
config/api_keys.json: interface, security, presence, accounts, remote.
Every control writes through memory.config_manager and takes effect
immediately unless its label says otherwise.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from .base import C, FONT_HEAD, FONT_MONO, FONT_UI


def _cfg() -> dict:
    from memory.config_manager import load_api_keys
    return load_api_keys()


def _set(key: str, value) -> None:
    from memory.config_manager import _save_flag
    _save_flag(key, value)


def _btn(text: str, kind: str = "dim") -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(28)
    b.setFont(QFont(FONT_UI, 9, QFont.Weight.Bold))
    col = {"pri": C.PRI, "ok": C.LIVE, "bad": C.MUTED_C}.get(kind, C.TEXT_MED)
    b.setStyleSheet(f"""
        QPushButton {{ background: transparent; color: {col}; border: 1px solid {C.BORDER_A};
            border-radius: 3px; padding: 0 12px; }}
        QPushButton:hover {{ border-color: {col}; background: {C.PRI_GHO}; }}
        QPushButton:disabled {{ color: {C.BORDER_B}; border-color: {C.BORDER}; }}""")
    return b


def _note(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setFont(QFont(FONT_UI, 10))
    lab.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
    return lab


class SettingsOverlay(QWidget):
    _OW, _OH = 560, 470
    _status_sig = pyqtSignal(str, str)        # (which label, text) from worker threads
    _ui_call = pyqtSignal(object)             # worker thread → run a callable on the Qt thread

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._ui_call.connect(lambda fn: fn())
        self._win = window
        self.setFixedSize(self._OW, self._OH)
        self.setObjectName("SettingsOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QWidget#SettingsOverlay {{ background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B}; border-radius: 6px; }}
            QTabWidget::pane {{ border: 1px solid {C.BORDER_A}; border-radius: 3px; top: -1px; }}
            QTabBar::tab {{ background: transparent; color: {C.TEXT_DIM}; padding: 6px 12px;
                font-family: '{FONT_UI}'; font-size: 10pt; font-weight: 700;
                border: 1px solid transparent; border-bottom: none; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-color: {C.BORDER_A};
                background: {C.PANEL}; }}
            QCheckBox {{ color: {C.TEXT}; font-family: '{FONT_UI}'; font-size: 10pt; spacing: 8px; }}
            QComboBox {{ background: {C.PANEL}; color: {C.WHITE}; border: 1px solid {C.BORDER_A};
                border-radius: 3px; padding: 3px 6px; font-family: '{FONT_UI}'; }}
            QListWidget {{ background: {C.PANEL}; color: {C.TEXT_MED}; border: 1px solid {C.BORDER_A};
                border-radius: 4px; font-family: '{FONT_UI}'; font-size: 10pt; padding: 4px; }}
            QListWidget::item {{ border-bottom: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO}; }}
        """)
        self._labels: dict[str, QLabel] = {}
        self._status_sig.connect(lambda k, t: self._labels[k].setText(t) if k in self._labels else None)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        title = QLabel("SYSTEM SETTINGS")
        tf = QFont(FONT_HEAD, 11, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        title.setFont(tf)
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._interface_tab(), "INTERFACE")
        tabs.addTab(self._security_tab(), "SECURITY")
        tabs.addTab(self._presence_tab(), "PRESENCE")
        tabs.addTab(self._accounts_tab(), "ACCOUNTS")
        tabs.addTab(self._remote_tab(), "REMOTE")
        root.addWidget(tabs, stretch=1)
        self._tabs = tabs

        row = QHBoxLayout(); row.addStretch()
        close = _btn("CLOSE"); close.clicked.connect(self._close)
        row.addWidget(close)
        root.addLayout(row)

    # ── tabs ─────────────────────────────────────────────────────────────────
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget(); w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(9)
        return w, lay

    def _check(self, lay, text: str, key: str, default: bool, on_change=None) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setChecked(bool(_cfg().get(key, default)))

        def changed(v):
            _set(key, bool(v))
            if on_change:
                on_change(bool(v))
        cb.toggled.connect(changed)
        lay.addWidget(cb)
        return cb

    def _interface_tab(self) -> QWidget:
        w, lay = self._page()
        row = QHBoxLayout()
        row.addWidget(_note("HUD centrepiece"))
        self._style = QComboBox()
        from memory.config_manager import HUD_STYLES, get_hud_style
        names = {"sphere": "Holo-Sphere", "ring": "Voice Ring", "core": "Reactor core",
                 "face": "Animated face (legacy)"}
        for s in HUD_STYLES:
            self._style.addItem(names.get(s, s), s)
        self._style.setCurrentIndex(self._style.findData(get_hud_style()))
        self._style.currentIndexChanged.connect(self._style_changed)
        row.addWidget(self._style, stretch=1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(_note("Response speed"))
        self._speed = QComboBox()
        from memory.config_manager import RESPONSE_SPEEDS, get_response_speed
        labels = {"balanced": "Balanced — ignores chatter not aimed at me",
                  "fast": "Fast — answers after a short pause (default)",
                  "fastest": "Fastest — may cut in if you pause mid-sentence"}
        for s in RESPONSE_SPEEDS:
            self._speed.addItem(labels[s], s)
        self._speed.setCurrentIndex(self._speed.findData(get_response_speed()))
        self._speed.currentIndexChanged.connect(self._speed_changed)
        row2.addWidget(self._speed, stretch=1)
        lay.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(_note("Animation"))
        self._anim = QComboBox()
        from memory.config_manager import ANIM_MODES, get_anim_mode
        anim_labels = {"smooth": "Smooth — up to 60 fps (default)",
                       "balanced": "Balanced — about half the frames and CPU",
                       "saver": "Power saver — lowest CPU, choppier"}
        for m in ANIM_MODES:
            self._anim.addItem(anim_labels[m], m)
        self._anim.setCurrentIndex(self._anim.findData(get_anim_mode()))
        self._anim.currentIndexChanged.connect(self._anim_changed)
        row3.addWidget(self._anim, stretch=1)
        lay.addLayout(row3)
        row4 = QHBoxLayout()
        row4.addWidget(_note("Interrupt him by"))
        self._barge = QComboBox()
        from memory.config_manager import BARGE_MODES, get_barge_mode
        barge_labels = {"name": "Saying his name — “Jarvis” / “Hey Jarvis” (default)",
                        "voice": "Any voice — fastest, but noise can cut him off",
                        "off": "Off — only Esc or the INTERRUPT button"}
        for m in BARGE_MODES:
            self._barge.addItem(barge_labels[m], m)
        self._barge.setCurrentIndex(self._barge.findData(get_barge_mode()))
        self._barge.currentIndexChanged.connect(self._barge_changed)
        row4.addWidget(self._barge, stretch=1)
        lay.addLayout(row4)
        self._check(lay, "Sound effects (chirps, ticks, alerts)", "sfx_enabled", True)
        self._check(lay, "Close to the tray instead of quitting", "close_to_tray", False)
        self._check(lay, "Borderless window (applies on restart)", "frameless", True)
        lay.addWidget(_note("Theme, colour, voice and names live in ⚙ → Customise."))
        lay.addStretch()
        return w

    def _speed_changed(self) -> None:
        """Save, then rebuild the live session so it applies now (the same
        path a voice change takes; the conversation is resumed)."""
        from memory.config_manager import save_response_speed
        save_response_speed(self._speed.currentData())
        cb = getattr(self._win, "on_voice_change", None)
        if callable(cb):
            cb()

    def _barge_changed(self) -> None:
        from memory.config_manager import save_barge_mode
        mode = self._barge.currentData()
        save_barge_mode(mode)
        cb = getattr(self._win, "on_barge_change", None)
        if callable(cb):
            cb(mode)                              # applies to the next sentence

    def _anim_changed(self) -> None:
        from memory.config_manager import save_anim_mode
        mode = self._anim.currentData()
        save_anim_mode(mode)
        self._win.hud.anim_mode = mode            # applies on the next frame

    def _style_changed(self) -> None:
        from memory.config_manager import save_hud_style
        style = self._style.currentData()
        save_hud_style(style)
        self._win.hud.hud_style = style
        try:
            self._win._refresh_hud_btn()
        except Exception:
            pass

    def _security_tab(self) -> QWidget:
        w, lay = self._page()
        self._check(lay, "Security watch — new network devices, USB drives, suspicious programs",
                    "security_watch_enabled", True)
        lay.addWidget(_note("Devices seen on your network:"))
        self._devices = QListWidget(); self._devices.setMinimumHeight(170)
        lay.addWidget(self._devices)
        self._fill_devices()
        self._labels["guest"] = _note("")
        lay.addWidget(self._labels["guest"])
        row = QHBoxLayout()
        lock = _btn("LOCK DOWN NOW", "bad"); lock.clicked.connect(self._lock)
        unlock = _btn("UNLOCK"); unlock.clicked.connect(self._unlock)
        row.addWidget(lock); row.addWidget(unlock); row.addStretch()
        lay.addLayout(row)
        self._refresh_guest()
        lay.addStretch()
        return w

    def _fill_devices(self) -> None:
        """One row per device: an icon, its name (or 'Unnamed device'), and
        the address details underneath in small type."""
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QListWidgetItem
        self._devices.clear()
        try:
            from core.security_watch import get_watch
            known = get_watch()._known
        except Exception:
            known = {}
        if not known:
            self._devices.addItem("No devices recorded yet — the watch scans once a minute.")
            return
        for mac, info in sorted(known.items(), key=lambda kv: kv[1].get("ip", "")):
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            h = QHBoxLayout(row); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(10)
            icon = QLabel("◉")
            icon.setFont(QFont(FONT_UI, 12))
            icon.setStyleSheet(f"color: {C.PRI}; background: transparent;")
            h.addWidget(icon)
            col = QVBoxLayout(); col.setSpacing(0)
            name = QLabel(info.get("name") or "Unnamed device")
            name.setFont(QFont(FONT_UI, 10, QFont.Weight.DemiBold))
            name.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
            first = str(info.get("first_seen") or "")[:16].replace("T", " ")
            detail = QLabel(f"{info.get('ip', '?')}   ·   {mac}" + (f"   ·   since {first}" if first else ""))
            detail.setFont(QFont(FONT_MONO, 8))
            detail.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            col.addWidget(name); col.addWidget(detail)
            h.addLayout(col, 1)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 42))
            item.setToolTip(f"{info.get('ip', '?')}  {mac}")
            self._devices.addItem(item)
            self._devices.setItemWidget(item, row)

    def _refresh_guest(self) -> None:
        from core.access import get_guard
        g = get_guard()
        self._labels["guest"].setText(
            f"Guest mode is ON ({g.reason}). Unlock checks your face, or asks for an "
            f"on-screen confirmation if no face is enrolled." if g.guest else
            "Owner access. Lock down restricts messages, files, memory, protocols and "
            "accounts until you are verified again.")

    def _lock(self) -> None:
        from core.access import get_guard
        get_guard().enter_guest("locked down from settings")
        self._refresh_guest()

    def _unlock(self) -> None:
        from plugins.access_control import run as access_run

        def go():
            out = access_run({"action": "unlock"})
            self._status_sig.emit("guest", out.split(". Say")[0].split(" Confirm")[0])
        threading.Thread(target=go, daemon=True, name="settings-unlock").start()

    def _presence_tab(self) -> QWidget:
        w, lay = self._page()
        from core.presence import get_presence
        pr = get_presence()
        self._presence_cb = self._check(
            lay, "Presence — welcome me back, notice strangers (uses the webcam)",
            "presence_enabled", False)
        self._presence_cb.setEnabled(pr.enrolled())
        self._labels["presence"] = _note(pr.status())
        lay.addWidget(self._labels["presence"])
        lay.addWidget(_note("Learning your face looks through the camera for a few seconds and "
                            "stores 128 numbers, never a photo. The first time downloads a 37 MB "
                            "model."))
        row = QHBoxLayout()
        learn = _btn("LEARN MY FACE", "pri"); learn.clicked.connect(self._enroll)
        forget = _btn("FORGET MY FACE", "bad"); forget.clicked.connect(self._forget)
        row.addWidget(learn); row.addWidget(forget); row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _enroll(self) -> None:
        from core.presence import get_presence
        self._labels["presence"].setText("Look at the camera…")

        def go():
            try:
                msg = get_presence().enroll(log=lambda m: self._status_sig.emit("presence", m))
            except Exception as e:
                msg = f"Enrolment failed: {e}"
            self._status_sig.emit("presence", msg)
            # (QTimer.singleShot from this worker thread would never fire.)
            self._ui_call.emit(lambda: self._presence_cb.setEnabled(get_presence().enrolled()))
        threading.Thread(target=go, daemon=True, name="settings-enroll").start()

    def _forget(self) -> None:
        from core.presence import get_presence
        self._labels["presence"].setText(get_presence().forget())
        self._presence_cb.blockSignals(True)
        self._presence_cb.setChecked(False)
        self._presence_cb.setEnabled(False)
        self._presence_cb.blockSignals(False)

    def _accounts_tab(self) -> QWidget:
        w, lay = self._page()
        from core import google_services as g
        self._labels["google"] = _note("")
        lay.addWidget(_note("GOOGLE — calendar and mail, read-only"))
        lay.addWidget(self._labels["google"])
        row = QHBoxLayout()
        self._g_connect = _btn("CONNECT", "pri"); self._g_connect.clicked.connect(self._google_connect)
        self._g_disconnect = _btn("DISCONNECT", "bad")
        self._g_disconnect.clicked.connect(self._google_disconnect)
        row.addWidget(self._g_connect); row.addWidget(self._g_disconnect); row.addStretch()
        lay.addLayout(row)
        self._refresh_google()
        lay.addStretch()
        return w

    def _refresh_google(self) -> None:
        from core import google_services as g
        st = g.status()
        self._labels["google"].setText({
            "ready": "Connected. JARVIS can read your calendar and inbox; it cannot send, delete or change anything.",
            "needs_consent": "Client installed. Press Connect and approve read-only access in the browser.",
            "needs_client": g.SETUP_HELP}[st])
        self._g_connect.setEnabled(st == "needs_consent")
        self._g_disconnect.setEnabled(st == "ready")

    def _google_connect(self) -> None:
        from core import google_services as g
        self._labels["google"].setText("Opening the Google sign-in page in your browser…")

        def go():
            self._status_sig.emit("google", g.connect())
            self._ui_call.emit(self._refresh_google)
        threading.Thread(target=go, daemon=True, name="settings-google").start()

    def _google_disconnect(self) -> None:
        from core import google_services as g
        g.disconnect()
        self._refresh_google()

    def _remote_tab(self) -> QWidget:
        w, lay = self._page()
        lay.addWidget(_note("TERMINAL — from any command prompt in the JARVIS folder (or add it to PATH):"))
        cmds = QLabel('jarvis "what\'s on my calendar"\njarvis --protocol work\n'
                      'jarvis --status\njarvis --summon')
        cmds.setFont(QFont(FONT_MONO, 9))
        cmds.setStyleSheet(f"color: {C.PRI}; background: {C.PANEL}; border: 1px solid {C.BORDER_A};"
                           f" border-radius: 3px; padding: 8px;")
        lay.addWidget(cmds)
        lay.addWidget(_note("It talks to the running app over 127.0.0.1 only, with a new secret "
                            "every launch."))
        lay.addWidget(_note("PHONE — press Remote Control in ⚙ to start the dashboard (local "
                            "network only) and show the pairing QR code."))
        lay.addWidget(_note("SUMMON — Ctrl+Alt+J from any app."))
        lay.addStretch()
        return w

    def _close(self) -> None:
        self.hide()
        self.deleteLater()
