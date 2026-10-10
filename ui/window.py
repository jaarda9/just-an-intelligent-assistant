"""MainWindow: the top-level Qt window that lays out and wires every panel."""
from __future__ import annotations

import json
import math
import os
import platform
import psutil
import subprocess
import sys
import threading
import time
from PyQt6.QtCore import QEvent, QPoint, QSizeF, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)
from pathlib import Path

from .base import (
    API_FILE, APP_PROTOCOL, APP_VERSION, C, CONFIG_DIR, DEFAULT_UI_COLOR,
    HAVE_VIDEO, QAudioOutput, QGraphicsVideoItem, QMediaPlayer, _DEFAULT_H, _DEFAULT_W,
    _LEFT_W, _MIN_H, _MIN_W, _OS, _RIGHT_W, _read_full_config,
    _sfx, apply_ui_accent, current_palette, retheme_all_widgets,
    load_fonts, FONT_UI, FONT_HEAD, FONT_MONO,
)
from .metrics import (
    _metrics,
)
from .hud import (
    HudCanvas,
)
from .window_media import MediaMixin
from .window_desktop import DesktopMixin
from .window_chrome import ChromeMixin
from .window_content import ContentMixin
from .window_drawers import DrawersMixin
from .window_overlays import OverlaysMixin
from .chrome import GlassPanel, IconButton, StatusChip, ToastManager, WindowButton, glow
from .widgets import (
    FileDropZone, LogWidget, MetricBar, _CameraPreview, _FILE_ICONS, _file_category,
    _fmt_size,
)
from .overlays_setup import (
    AudioDeviceOverlay, ConfirmBanner, CustomizeOverlay, PluginManagerOverlay, SetupOverlay,
)
from .overlays_data import (
    ClipboardPanel, MemoryOverlay, PluginSettingsOverlay, RemoteKeyOverlay,
)

class MainWindow(MediaMixin, DesktopMixin, ChromeMixin, ContentMixin, DrawersMixin, OverlaysMixin, QMainWindow):
    _log_sig        = pyqtSignal(str)
    _toast_sig      = pyqtSignal(str, str, str)   # (title, text, level) — thread-safe
    _summon_sig     = pyqtSignal()                # global hotkey thread → UI thread
    _media_sig      = pyqtSignal(object)          # media watcher thread → Now Playing
    _state_sig      = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _reconfig_sig   = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)      # live camera frame → HUD area
    _video_open_sig  = pyqtSignal(str, str, bool, str)  # video, title, muted, audio
    _wake_btns_sig   = pyqtSignal()          # wake state resolved off-thread
    _video_close_sig = pyqtSignal()
    _video_mute_sig  = pyqtSignal(bool)
    _clipboard_sig  = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _confirm_sig    = pyqtSignal(str, str)   # (title, detail) — irreversible-action gate
    _confirm_hide_sig = pyqtSignal()
    _wake_dl_sig    = pyqtSignal(bool, str)  # wake-word install finished (ok, message)
    _quiz_sig       = pyqtSignal(str, object, object)  # (topic, questions, grader)
    _quiz_hide_sig  = pyqtSignal()
    _review_sig     = pyqtSignal(str, str, object, object)  # document review payload

    def __init__(self, face_path: str):
        super().__init__()
        load_fonts()
        self._face_path = face_path

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        # Apply the saved UI colour BEFORE panels/stylesheets are built
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display} — {APP_VERSION}")
        self._apply_frameless()
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self.get_plugin_settings = None # callable: () -> list[dict] settings schemas, set by JarvisLive
        self.on_wake_toggle    = None   # callable: (enable: bool) -> str, set by JarvisLive
        self.on_wake_manual    = None   # callable: () -> None — manual sleep/wake
        self.on_push_to_talk   = None   # callable: (enable: bool) -> str scope
        self.ptt_hold          = None   # callable: (held: bool) -> None — windowed chord
        self.wake_get_state    = None   # callable: () -> dict {enabled, awake, ready}
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path, _display)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()
        self._quiz_panel = self._build_quiz_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Rajdhani", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Rajdhani", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # ── Video surface ────────────────────────────────────────────────
        # Built exactly like the camera page above and stacked beside it,
        # because it is the same idea: something takes the centre of the HUD
        # for a while and then gives it back. Sharing the stack rather than
        # inventing a second mechanism means the avatar, the camera and a video
        # can never be on screen at once.
        self._video_split = False        # is the sound a separate stream?
        self._video_auto_muted = False   # did JARVIS close the mic, or the user?
        # A plain flag rather than reading the widget. video_is_playing() is
        # called from plugin threads, and reading a widget's state from one is
        # not something to rely on; an attribute is.
        self._video_on = False
        self._video_cont = QWidget()
        self._video_cont.setStyleSheet(f"background: {C.BG};")
        _vid_v = QVBoxLayout(self._video_cont)
        _vid_v.setContentsMargins(8, 6, 8, 8)
        _vid_v.setSpacing(4)

        _vid_hdr = QHBoxLayout()
        self._video_title = QLabel("▶  VIDEO")
        self._video_title.setFont(QFont("Rajdhani", 9, QFont.Weight.Bold))
        self._video_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _vid_hdr.addWidget(self._video_title)
        _vid_hdr.addStretch()

        def _vid_btn(text: str) -> QPushButton:
            b = QPushButton(text)
            b.setFont(QFont("Rajdhani", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    color: {C.TEXT_DIM}; background: transparent;
                    border: none; padding: 2px 6px;
                }}
                QPushButton:hover {{ color: {C.PRI}; }}
            """)
            return b

        # Muted is the default and the button says so, because a soundtrack
        # talking over JARVIS is the one way this feature could make the
        # assistant worse rather than better.
        self._video_mute_btn = _vid_btn("🔇  SOUND OFF")
        self._video_mute_btn.clicked.connect(self._toggle_video_mute)
        _vid_hdr.addWidget(self._video_mute_btn)

        _vid_x = _vid_btn("✕  CLOSE")
        _vid_x.clicked.connect(self.stop_video)
        _vid_hdr.addWidget(_vid_x)
        _vid_v.addLayout(_vid_hdr)

        if HAVE_VIDEO:
            # A GRAPHICS ITEM, NOT A QVideoWidget.
            #
            # QVideoWidget gets a native window of its own, and a native window
            # is painted by the compositor above every ordinary widget that
            # shares the screen with it — so the settings drawer opened
            # *underneath* the video and raise_() could not help, because the
            # two are not in the same painting order at all. A video item drawn
            # into a QGraphicsView goes through Qt's own painter like any other
            # widget, and anything laid over it stays over it.
            self._video_scene = QGraphicsScene(self)
            self._video_item = QGraphicsVideoItem()
            self._video_scene.addItem(self._video_item)
            self._video_widget = QGraphicsView(self._video_scene)
            self._video_widget.setStyleSheet("background: #000; border: none;")
            self._video_widget.setFrameShape(QGraphicsView.Shape.NoFrame)
            self._video_widget.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._video_widget.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._video_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            _vid_v.addWidget(self._video_widget, stretch=1)

            self._video_audio = QAudioOutput()
            self._video_audio.setMuted(True)
            self._video_player = QMediaPlayer()
            self._video_player.setVideoOutput(self._video_item)
            # Keep the picture filling the view as the window is resized.
            self._video_item.nativeSizeChanged.connect(self._fit_video)
            self._video_player.setAudioOutput(self._video_audio)
            self._video_player.errorOccurred.connect(self._on_video_error)

            # A SECOND player, for sound that arrives separately.
            #
            # YouTube no longer serves a single stream carrying both picture and
            # sound — not for new uploads and not for old ones; checked against
            # three videos including the oldest on the site, and every one of
            # them offered zero combined formats. Picture and sound are two
            # URLs, so they are two players, started together and nudged back
            # into line by the timer below.
            #
            # A local file or a direct video URL still uses the first player
            # alone: one stream, one player, nothing to synchronise.
            self._video_sound = QMediaPlayer()
            self._video_sound_out = QAudioOutput()
            self._video_sound_out.setMuted(True)
            self._video_sound.setAudioOutput(self._video_sound_out)

            self._video_sync = QTimer(self)
            self._video_sync.setInterval(1000)
            self._video_sync.timeout.connect(self._sync_video_sound)
        else:
            self._video_scene = None
            self._video_item = None
            self._video_widget = None
            self._video_player = None
            self._video_audio = None
            self._video_sound = None
            self._video_sound_out = None
            self._video_sync = None
            _miss = QLabel("Video playback is not available in this Qt install.")
            _miss.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _miss.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            _vid_v.addWidget(_miss, stretch=1)

        # Stack: 0 = animated HUD, 1 = live camera, 2 = video
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)
        self._hud_cam_stack.addWidget(self._video_cont)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.addWidget(self._quiz_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        # In-HUD notifications, stacked at the top-right of the centre column.
        self._toasts = ToastManager(central, self._hud_cam_stack)
        self._toast_sig.connect(self._show_toast)

        # Ways back in: tray icon + global summon hotkey (Mark IV).
        self.run_tool = None          # set by JarvisLive — tray protocols use it
        self.get_tool_catalog = None  # set by JarvisLive — protocol editor's step picker
        self._setup_access_points()

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._ctrl_drawer = self._build_controls_drawer()
        self._warm_wake_state()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metric update timer
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._confirm_sig.connect(self._show_confirm_banner)
        self._confirm_hide_sig.connect(self._hide_confirm_banner)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._wake_btns_sig.connect(self._refresh_wake_btns)
        self._video_open_sig.connect(self._on_video_open)
        self._video_close_sig.connect(self._on_video_close)
        self._video_mute_sig.connect(self._on_video_mute)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._wake_dl_sig.connect(self._on_wake_install_done)
        self._quiz_sig.connect(self._show_quiz)
        self._quiz_hide_sig.connect(self._hide_quiz)
        self._review_sig.connect(self._show_review)
        self._cam_stop = threading.Event()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()      # boot sequence runs when setup completes
        else:
            # A beat after construction, so the window is on screen when the
            # tone and the first frame of the animation land.
            QTimer.singleShot(300, self._start_boot)

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_mini = QShortcut(QKeySequence("F9"), self)
        sc_mini.activated.connect(self.enter_mini)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_toasts"):
            self._toasts.relayout()
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()
        if hasattr(self, '_ctrl_drawer') and self._ctrl_drawer.isVisible():
            self._position_ctrl_drawer()
        self._fit_video()

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    HEADER_H = 58

    def _build_header(self) -> QWidget:
        """Command bar: wordmark, the two drawer buttons, clock, and — the
        window being frameless — the window controls. Dragging the bar moves
        the window; double-clicking it maximises."""
        w = QWidget()
        w.setObjectName("HeaderBar")
        w.setFixedHeight(self.HEADER_H)
        w.setStyleSheet(f"""
            QWidget#HeaderBar {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {C.PANEL}, stop:1 {C.BG});
                border-bottom: 1px solid {C.BORDER_A};
            }}""")
        w.installEventFilter(self)
        self._header = w
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 6, 0)
        lay.setSpacing(0)

        # wordmark
        mark = QVBoxLayout(); mark.setSpacing(0)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        tf = QFont(FONT_HEAD, 15, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self._title_lbl.setFont(tf)
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        glow(self._title_lbl, C.PRI, 16, 150)
        mark.addWidget(self._title_lbl)
        self._sub_lbl = QLabel("Just A Rather Very Intelligent System"
                               if _disp in ("JARVIS", "J.A.R.V.I.S")
                               else "Personal AI Assistant")
        sf = QFont(FONT_UI, 8, QFont.Weight.DemiBold)
        sf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        sf.setCapitalization(QFont.Capitalization.AllUppercase)
        self._sub_lbl.setFont(sf)
        self._sub_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        mark.addWidget(self._sub_lbl)
        lay.addLayout(mark)
        lay.addSpacing(18)

        ver = QLabel(APP_VERSION)
        ver.setFont(QFont(FONT_MONO, 8))
        ver.setFixedHeight(20)
        ver.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 0 6px;")
        lay.addWidget(ver, alignment=Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(12)

        self._drawer_btn = IconButton("gear")
        self._drawer_btn.setToolTip("Setup — things you set once")
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        # A SECOND drawer, and the split is by how often a thing is touched.
        #
        # One panel held twelve buttons: the ones you press once when you set
        # the assistant up sitting next to the ones you flick on and off every
        # day. Separating them by that — setup behind ⚙, everyday behind 🎛 —
        # is what makes each list short enough to read at a glance.
        self._ctrl_btn = IconButton("sliders")
        self._ctrl_btn.setToolTip("Controls — the everyday switches")
        self._ctrl_btn.clicked.connect(self._toggle_controls)
        lay.addSpacing(6)
        lay.addWidget(self._ctrl_btn)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(0)
        right_col.addStretch()
        self._clock_lbl = QLabel("00:00:00")
        cf = QFont(FONT_MONO, 17)
        cf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self._clock_lbl.setFont(cf)
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        glow(self._clock_lbl, C.PRI, 12, 120)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        df = QFont(FONT_UI, 8, QFont.Weight.DemiBold)
        df.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        df.setCapitalization(QFont.Capitalization.AllUppercase)
        self._date_lbl.setFont(df)
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        right_col.addStretch()
        lay.addLayout(right_col)
        lay.addSpacing(14)

        # window controls (frameless window — see _apply_frameless)
        ctl = QHBoxLayout(); ctl.setSpacing(0)
        for kind, slot in (("mini", self.enter_mini),
                           ("min", self.showMinimized),
                           ("max", self._toggle_maximized),
                           ("close", self.close)):
            b = WindowButton(kind)
            b.clicked.connect(slot)
            ctl.addWidget(b, alignment=Qt.AlignmentFlag.AlignTop)
        self._win_ctl = ctl
        lay.addLayout(ctl)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("LeftCol")
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"QWidget#LeftCol {{ background: {C.BG}; }}")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 6, 10)
        lay.setSpacing(10)

        sysp = GlassPanel("Systems")
        self._bar_cpu = MetricBar("CPU", "PRI")
        self._bar_mem = MetricBar("MEM", "ACC2")
        self._bar_net = MetricBar("NET", "GREEN")
        self._bar_gpu = MetricBar("GPU", "ACC")
        self._bar_tmp = MetricBar("TMP", "#ff6688")
        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            sysp.body.addWidget(bar)

        info = QHBoxLayout(); info.setSpacing(6)
        self._uptime_lbl = QLabel("UP  --:--")
        self._proc_lbl = QLabel("PROC  --")
        for lbl, col in ((self._uptime_lbl, C.GREEN), (self._proc_lbl, C.TEXT_MED)):
            lbl.setFont(QFont(FONT_MONO, 8))
            lbl.setStyleSheet(f"color: {col}; background: transparent; border: none;")
            info.addWidget(lbl)
        info.addStretch()
        sysp.body.addLayout(info)
        lay.addWidget(sysp)

        # Live status — replaces three static badges that always said
        # "ACTIVE / CLEARED" whatever was actually happening.
        stp = GlassPanel("Status")
        self._chip_voice = StatusChip("Voice link")
        self._chip_sec = StatusChip("Security")
        self._chip_presence = StatusChip("Presence")
        self._chip_access = StatusChip("Access")
        for chip in (self._chip_voice, self._chip_sec, self._chip_presence, self._chip_access):
            stp.body.addWidget(chip)
        lay.addWidget(stp)

        # Now Playing — appears only while some app is playing media.
        from .nowplaying import NowPlayingPanel
        from core.media import MediaWatcher
        self._now_playing = NowPlayingPanel()
        lay.addWidget(self._now_playing)
        self._media_sig.connect(self._now_playing.show_info)
        self._media_watch = MediaWatcher(self._media_sig.emit)
        self._media_watch.start()
        lay.addStretch()

        self._chip_timer = QTimer(self)
        self._chip_timer.timeout.connect(self._refresh_status_chips)
        self._chip_timer.start(2000)
        QTimer.singleShot(200, self._refresh_status_chips)
        return w

    def _refresh_status_chips(self) -> None:
        """Pull live state for the STATUS panel. Cheap: config reads and
        in-memory flags only — nothing here scans the network or the camera."""
        try:
            state = getattr(self.hud, "state", "INITIALISING")
            if self._muted:
                self._chip_voice.set("warn", "mic muted")
            elif state == "SLEEPING":
                self._chip_voice.set("off", "standby")
            elif state in ("LISTENING", "SPEAKING", "THINKING", "PROCESSING"):
                self._chip_voice.set("ok", state.lower())
            else:
                self._chip_voice.set("warn", "connecting")
        except Exception:
            pass
        try:
            from core.security_watch import get_watch
            w = get_watch()
            if w.enabled():
                n = len(w._known)
                self._chip_sec.set("ok", f"watching · {n} device{'s' if n != 1 else ''}"
                                   if n else "watching")
            else:
                self._chip_sec.set("off", "off")
        except Exception:
            self._chip_sec.set("off", "unavailable")
        try:
            from core.presence import get_presence
            pr = get_presence()
            if not pr.enrolled():
                self._chip_presence.set("off", "not set up")
            elif not pr.enabled():
                self._chip_presence.set("off", "off")
            else:
                here = getattr(pr, "_here", None)
                self._chip_presence.set(
                    "ok" if here else "info",
                    {True: "at the desk", False: "away", None: "watching"}[here])
        except Exception:
            self._chip_presence.set("off", "unavailable")
        try:
            from core.access import get_guard
            g = get_guard()
            self._chip_access.set("warn", "guest mode") if g.guest else self._chip_access.set("ok", "owner")
        except Exception:
            self._chip_access.set("off", "unavailable")
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("RightCol")
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"QWidget#RightCol {{ background: {C.BG}; }}")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 10, 10, 10)
        lay.setSpacing(10)

        comms = GlassPanel("Comms")
        self._log = LogWidget()
        comms.body.addWidget(self._log, stretch=1)
        lay.addWidget(comms, stretch=1)

        cmd = GlassPanel("Command")
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        cmd.body.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded")
        self._file_hint.setFont(QFont(FONT_UI, 8))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._file_hint.setWordWrap(True)
        cmd.body.addWidget(self._file_hint)

        cmd.body.addLayout(self._build_input_row())

        # Interrupt and microphone side by side, outlined rather than filled:
        # always available, never shouting.
        row = QHBoxLayout(); row.setSpacing(6)
        self._interrupt_btn = QPushButton("✋  INTERRUPT  ·  ESC")
        self._interrupt_btn.setFixedHeight(32)
        bf = QFont(FONT_UI, 9, QFont.Weight.Bold)
        bf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        self._interrupt_btn.setFont(bf)
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.MUTED_C};
                border: 1px solid #5a1a2a; border-radius: 4px;
            }}
            QPushButton:hover {{
                background: #1a0610; border: 1px solid {C.MUTED_C};
            }}
            QPushButton:pressed {{ background: #2a0a18; }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        row.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MIC LIVE")
        self._mute_btn.setFixedHeight(32)
        self._mute_btn.setFont(bf)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        row.addWidget(self._mute_btn)
        cmd.body.addLayout(row)
        lay.addWidget(cmd)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Talk to me, or type a command…")
        self._input.setFont(QFont(FONT_UI, 10, QFont.Weight.Medium))
        self._input.setFixedHeight(34)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL}; color: {C.WHITE};
                border: 1px solid {C.BORDER_A}; border-radius: 4px; padding: 3px 10px;
                selection-background-color: {C.PRI_DIM};
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; background: {C.PANEL2}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(34, 34)
        send.setFont(QFont("Rajdhani", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setObjectName("FooterBar")
        w.setFixedHeight(24)
        w.setStyleSheet(f"QWidget#FooterBar {{ background: {C.BG}; "
                        f"border-top: 1px solid {C.BORDER}; }}")
        lay = QHBoxLayout(w); lay.setContentsMargins(16, 0, 16, 0)

        def _fl(txt, color=C.TEXT_DIM, mono=False):
            l = QLabel(txt)
            f = QFont(FONT_MONO, 8) if mono else QFont(FONT_UI, 8, QFont.Weight.DemiBold)
            if not mono:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
            l.setFont(f)
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("CTRL+ALT+J SUMMON   ·   F4 MUTE   ·   F9 MINI-MODE   ·   "
                          "F11 FULLSCREEN   ·   CTRL+SPACE PUSH-TO-TALK"))
        lay.addStretch()
        lay.addWidget(_fl(f"{APP_VERSION}  ·  BASED ON MARK LV BY FATIHMAKES", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell {self._assistant_name} what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        # A deliberate press settles the question: whatever the video did, or is
        # about to do, the user has now said what they want.
        self._video_auto_muted = False
        self._set_muted(not self._muted)

    def _set_muted(self, muted: bool, note: str = ""):
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.hud.muted = muted
        self._style_mute_btn()
        if getattr(self, "_tray", None) is not None:
            self._tray.refresh()
        if muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted." + (f" {note}" if note else ""))
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active." + (f" {note}" if note else ""))

    def _style_mute_btn(self):
        # Muted is the state worth noticing, so it is the filled one; live is
        # a quiet outline.
        if self._muted:
            self._mute_btn.setText("🔇  MIC MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #1a0610; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 4px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MIC LIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.GREEN};
                    border: 1px solid #0d4a30; border-radius: 4px;
                }}
                QPushButton:hover {{ background: #021a10; border: 1px solid {C.GREEN}; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        prev = self.hud.state
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        if _sfx is not None:
            _sfx.on_state_change(prev, state)
        if getattr(self, "_tray", None) is not None:
            self._tray.refresh()

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov
        # Built during __init__, before the layout has its final size, so the
        # geometry above is computed against a placeholder width. Re-centre
        # once the window is actually on screen.
        QTimer.singleShot(0, self._center_setup_overlay)

    def showEvent(self, e):
        super().showEvent(e)
        self._center_setup_overlay()

    def _center_setup_overlay(self):
        ov = getattr(self, "_overlay", None)
        if ov is None or not ov.isVisible():
            return
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._start_boot()
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. {self._assistant_name} online.")
