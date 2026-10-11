"""Small reusable widgets: metric bars, activity log, file drop zone, camera preview."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QPainter,
    QPen, QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)
import re
import time
from collections import deque
from pathlib import Path

from .base import (
    C, FONT_MONO, FONT_UI, _OS, qcol,
)

class MetricBar(QWidget):
    """One SYSTEMS row: label, value, a live mini-graph of the last ~90 s and
    a thin level track. One colour language: the accent normally, amber when
    the reading runs high, red only when it is critical."""

    HISTORY = 48            # samples (one per metrics tick, every 2 s)
    WARN_AT, CRIT_AT = 70.0, 90.0

    def __init__(self, label: str, color: str = "PRI", parent=None, graph: bool = True):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._graph = graph
        self._value = 0.0       # 0–100
        self._text  = "--"
        self._hist: deque = deque(maxlen=self.HISTORY)
        self.setFixedHeight(34 if graph else 30)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        v = max(0.0, min(100.0, pct))
        self._hist.append(v)
        if v == self._value and text == self._text and not self._graph:
            return          # unchanged — skip the repaint
        self._value = v
        self._text  = text
        self.update()

    def _level_colour(self) -> QColor:
        if self._value >= self.CRIT_AT:
            return qcol(C.RED)
        if self._value >= self.WARN_AT:
            return qcol(C.WARN)
        # A palette key ("PRI") follows live re-theming; a hex stays fixed.
        return qcol(getattr(C, self._color, self._color))

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        bar_h  = 3
        bar_y  = H - bar_h - 3
        bar_x  = 1
        bar_w  = W - 2
        fill_w = bar_w * self._value / 100
        bar_col = self._level_colour()

        # mini-graph behind the text: faint filled area, brighter top line
        if self._graph and len(self._hist) >= 2:
            g_top, g_bot = 3.0, bar_y - 2.0
            gh = g_bot - g_top
            n = self.HISTORY
            step = bar_w / max(1, n - 1)
            vals = list(self._hist)
            x0 = bar_x + bar_w - step * (len(vals) - 1)
            pts = [QPointF(x0 + i * step, g_bot - gh * v / 100.0) for i, v in enumerate(vals)]
            area = QPolygonF([QPointF(pts[0].x(), g_bot), *pts, QPointF(pts[-1].x(), g_bot)])
            fill = QColor(bar_col); fill.setAlpha(34)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPolygon(area)
            line = QColor(bar_col); line.setAlpha(120)
            p.setPen(QPen(line, 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF(pts))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1.5, 1.5)
        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1.5, 1.5)

        lf = QFont(FONT_UI, 9, QFont.Weight.Bold)
        lf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(lf)
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(2, 1, 60, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont(FONT_MONO, 10))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 1, W - 2, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()


def _tool_name(raw: str) -> str:
    """'[Search:web]' → 'search', '[open_app]' → 'open app'."""
    return raw.split(":")[0].strip().replace("_", " ").lower() or "tool"


class _Card(QFrame):
    """One turn in the transcript: who + time, then the text, then (for the
    assistant) the tools it used to get there."""

    def __init__(self, kind: str, who: str, text: str, tools=(), via: str = ""):
        super().__init__()
        self.kind = kind
        self.setObjectName("YouCard" if kind == "you" else "AiCard")
        if kind == "you":
            self.setStyleSheet(f"""
                QFrame#YouCard {{ background: {C.PANEL2}; border: 1px solid {C.BORDER};
                    border-radius: 6px; }}
                QLabel {{ background: transparent; border: none; }}""")
        else:
            self.setStyleSheet(f"""
                QFrame#AiCard {{ background: {C.PRI_GHO}; border: none;
                    border-left: 2px solid {C.PRI}; border-radius: 4px; }}
                QLabel {{ background: transparent; border: none; }}""")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 7)
        lay.setSpacing(2)

        head = QHBoxLayout(); head.setSpacing(6)
        who_l = QLabel(who.upper() + (f"  ·  {via}" if via else ""))
        hf = QFont(FONT_UI, 8, QFont.Weight.Bold)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        who_l.setFont(hf)
        who_l.setStyleSheet(f"color: {C.TEXT_MED if kind == 'you' else C.PRI};")
        head.addWidget(who_l)
        head.addStretch()
        when = QLabel(time.strftime("%H:%M"))
        when.setFont(QFont(FONT_MONO, 8))
        when.setStyleSheet(f"color: {C.TEXT_DIM};")
        head.addWidget(when)
        self.when = when
        self.live = False
        lay.addLayout(head)

        self.full_text = text
        self.body = QLabel(text if kind == "you" else "")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setFont(QFont(FONT_UI, 11, QFont.Weight.Medium))
        self.body.setStyleSheet(f"color: {C.WHITE if kind == 'you' else C.TEXT};")
        lay.addWidget(self.body)

        self.tools = QLabel("")
        self.tools.setWordWrap(True)
        self.tools.setFont(QFont(FONT_MONO, 8))
        self.tools.setStyleSheet(f"color: {C.PRI_DIM};")
        lay.addWidget(self.tools)
        self.set_tools(tools)

    def set_live(self, on: bool) -> None:
        """A live card is still being spoken: its words arrive as they are
        heard. The time label says so until the turn is final."""
        self.live = on
        if on:
            self.when.setText("● LIVE")
            self.when.setStyleSheet(f"color: {C.LIVE};")
        else:
            self.when.setText(time.strftime("%H:%M"))
            self.when.setStyleSheet(f"color: {C.TEXT_DIM};")

    def set_tools(self, tools) -> None:
        names, details = [], []
        for name, detail in tools:
            n = _tool_name(name)
            if n not in names:
                names.append(n)
            if detail:
                details.append(f"{n}: {detail}")
        self.tools.setText(("⚙ USED  " + "  ·  ".join(names)) if names else "")
        self.tools.setToolTip("\n".join(details[:12]))
        self.tools.setVisible(bool(names))


class LogWidget(QScrollArea):
    """COMMS transcript. Conversation turns are cards (yours on the right,
    the assistant's on the left with the tools it used underneath); system
    notes and errors are single quiet lines between them.

    Same interface as the old text log: append_log("You: …" / "JARVIS: …" /
    "SYS: …" / "ERR: …" / "[tool] detail" / "FILE: …"), safe from any thread.
    Tool lines arrive *before* the turn they belong to (they run while the
    model is still answering), so they are held and attached to the next
    assistant card — or shown on their own if no reply follows."""

    _sig = pyqtSignal(str)
    MAX_ENTRIES = 160
    TOOL_HOLD_MS = 25_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_A}; border-radius: 3px;
                min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self.viewport().setAutoFillBackground(False)
        self._inner = QWidget()
        self._inner.setObjectName("CommsInner")
        self._inner.setStyleSheet("QWidget#CommsInner { background: transparent; }")
        self._lay = QVBoxLayout(self._inner)
        self._lay.setContentsMargins(0, 2, 4, 2)
        self._lay.setSpacing(7)
        self._lay.addStretch(1)                       # entries sit at the bottom
        self.setWidget(self._inner)

        self._empty = QLabel("No conversation yet.\n\nSay “Jarvis…” or type below.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setFont(QFont(FONT_UI, 10, QFont.Weight.Medium))
        self._empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(self._empty)
        self._lay.addStretch(1)

        self._entries: list[QWidget] = []
        self._pending_tools: list[tuple[str, str]] = []
        self._tool_tmr = QTimer(self)
        self._tool_tmr.setSingleShot(True)
        self._tool_tmr.timeout.connect(self._flush_tools)
        self._ai_name_lc = "jarvis"   # updated when assistant name changes

        # Typewriter reveal for the assistant's newest card (≤ ~0.6 s).
        self._typing: _Card | None = None
        self._type_pos = 0
        self._type_tmr = QTimer(self)
        self._type_tmr.timeout.connect(self._type_step)

        # Follow new lines unless the user has scrolled up to read.
        self._stick = True
        sb = self.verticalScrollBar()
        sb.valueChanged.connect(lambda v: setattr(self, "_stick", v >= sb.maximum() - 24))
        sb.rangeChanged.connect(lambda _a, mx: self._stick and sb.setValue(mx))
        self._sig.connect(self._add)
        # Cards still being spoken, filled in as transcription arrives, and
        # finalised (not duplicated) when the turn's full line is logged.
        self._open: dict[str, _Card | None] = {"you": None, "ai": None}

    # ── public ───────────────────────────────────────────────────────────────
    def append_log(self, text: str):
        self._sig.emit(text)

    # Live updates travel the same queue as log lines, so a turn's final line
    # can never overtake (or be overtaken by) its own live updates.
    LIVE_TAG = "\x00LIVE:"

    def live(self, role: str, text: str) -> None:
        """Thread-safe: show the words of the turn in progress. role 'you' or
        'ai'; text is everything heard so far. live('end', '') closes both."""
        self._sig.emit(f"{self.LIVE_TAG}{role}:{text}")

    def _live(self, role: str, text: str) -> None:
        if role == "end":
            for r in ("you", "ai"):
                c = self._open.get(r)
                if c is not None:
                    self._close(r)
            return
        if role not in self._open or not text:
            return
        card = self._open[role]
        if card is None:
            if role == "ai":
                self._finish_typing()
                card = _Card("ai", (self._ai_name_lc or "jarvis").upper(), "",
                             tools=self._pending_tools)
                self._pending_tools = []
                self._tool_tmr.stop()
            else:
                card = _Card("you", "You", "")
            self._push(self._wrap(card, right=(role == "you")))
            self._open[role] = card
            card.set_live(True)
        card.full_text = text
        card.body.setText(text)

    def _close(self, role: str, final_text: str | None = None) -> None:
        card = self._open.get(role)
        self._open[role] = None
        if card is None:
            return
        try:
            if final_text:
                card.full_text = final_text
                card.body.setText(final_text)
            card.set_live(False)
        except RuntimeError:                  # card already deleted
            pass

    def entries(self) -> list[QWidget]:
        return list(self._entries)

    # ── parsing ──────────────────────────────────────────────────────────────
    def _classify(self, text: str):
        """→ (kind, body, extra). kind: you | ai | tool | file | err | sys."""
        t = (text or "").strip()
        tl = t.lower()
        m = re.match(r"you\s*(?:\(([^)]*)\))?\s*:\s*(?:\(([^)]*)\)\s*)?(.*)", t, re.I | re.S)
        if m:
            return "you", m.group(3).strip(), (m.group(1) or m.group(2) or "")
        m = re.match(r"\[web\]\s*:\s*(.*)", t, re.I | re.S)
        if m:
            return "you", m.group(1).strip(), "phone"
        for pfx in {f"{self._ai_name_lc}:", "jarvis:"}:
            if tl.startswith(pfx):
                return "ai", t[len(pfx):].strip(), ""
        m = re.match(r"\[([^\]]{1,40})\]\s*(.*)", t, re.S)
        if m:
            return "tool", m.group(2).strip(), m.group(1)
        if tl.startswith("file:"):
            return "file", t[5:].strip(), ""
        if tl.startswith("err"):
            return "err", t.split(":", 1)[-1].strip(), ""
        if tl.startswith("sys:"):
            return "sys", t[4:].strip(), ""
        return "sys", t, ""

    # ── building ─────────────────────────────────────────────────────────────
    def _add(self, text: str):
        if text.startswith(self.LIVE_TAG):
            role, _, live_text = text[len(self.LIVE_TAG):].partition(":")
            self._live(role, live_text)
            return
        kind, body, extra = self._classify(text)
        if kind == "tool":
            self._pending_tools.append((extra, body[:80]))
            self._tool_tmr.start(self.TOOL_HOLD_MS)
            return
        if not body:
            return
        if kind == "you":
            if self._open["you"] is not None and not extra:
                self._close("you", body)
                return
            self._push(self._wrap(_Card("you", "You", body, via=extra), right=True))
            return
        if kind == "ai":
            if self._open["ai"] is not None:
                card = self._open["ai"]
                if self._pending_tools:
                    card.set_tools(self._pending_tools)
                    self._pending_tools = []
                    self._tool_tmr.stop()
                self._close("ai", body)
                return
            self._finish_typing()
            name = (self._ai_name_lc or "jarvis").upper()
            card = _Card("ai", name, body, tools=self._pending_tools)
            self._pending_tools = []
            self._tool_tmr.stop()
            self._push(self._wrap(card, right=False))
            self._typing, self._type_pos = card, 0
            self._type_tmr.start(16)
            return
        self._push(self._line(kind, body))

    @staticmethod
    def _wrap(card: _Card, right: bool) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        if right:
            h.addSpacing(26)
        h.addWidget(card, 1)
        if not right:
            h.addSpacing(14)
        w.card = card
        return w

    @staticmethod
    def _line(kind: str, body: str, colour: str | None = None) -> QLabel:
        icon = {"err": "⚠", "file": "📎"}.get(kind, "·")
        col = colour or {"err": C.RED, "file": C.PRI}.get(kind, C.TEXT_DIM)
        lbl = QLabel(f"{time.strftime('%H:%M')}  {icon}  {body}")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setFont(QFont(FONT_UI, 9, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {col}; background: transparent; padding: 0 4px;")
        lbl.kind = kind
        return lbl

    def _flush_tools(self):
        """Tools that no reply claimed: show them as their own quiet line."""
        if not self._pending_tools:
            return
        names = []
        for n, _d in self._pending_tools:
            n = _tool_name(n)
            if n not in names:
                names.append(n)
        self._pending_tools = []
        lbl = self._line("tool", "⚙ " + "  ·  ".join(names), C.PRI_DIM)
        self._push(lbl)

    def _push(self, w: QWidget):
        self._empty.hide()
        # before the trailing stretch, so entries stack bottom-up
        self._lay.insertWidget(self._lay.count() - 1, w)
        self._entries.append(w)
        while len(self._entries) > self.MAX_ENTRIES:
            old = self._entries.pop(0)
            if getattr(old, "card", None) is self._typing:
                self._finish_typing()
            for r, c in self._open.items():
                if c is not None and getattr(old, "card", None) is c:
                    self._open[r] = None
            self._lay.removeWidget(old)
            old.deleteLater()

    def _type_step(self):
        card = self._typing
        if card is None:
            self._type_tmr.stop()
            return
        full = card.full_text
        step = max(3, len(full) // 36)
        self._type_pos = min(len(full), self._type_pos + step)
        card.body.setText(full[:self._type_pos])
        if self._type_pos >= len(full):
            self._finish_typing()

    def _finish_typing(self):
        if self._typing is not None:
            try:
                self._typing.body.setText(self._typing.full_text)
            except RuntimeError:          # card already deleted
                pass
        self._typing = None
        self._type_tmr.stop()


_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


FILE_FILTER = (
    "All Files (*.*);;"
    "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
    "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
    "Data (*.csv *.xlsx *.json *.xml);;"
    "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
    "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
    "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
    "Archives (*.zip *.rar *.tar *.gz *.7z)"
)


def pick_file(parent=None) -> str:
    """The file picker behind the drop zone and the 📎 button; '' if cancelled."""
    path, _ = QFileDialog.getOpenFileName(parent, "Select a file for JARVIS",
                                          str(Path.home()), FILE_FILTER)
    return path or ""


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        # The marching-ants dashed border is only meaningful while the user is
        # hovering or dragging a file over the zone. When idle, skip the repaint
        # entirely instead of redrawing the whole zone 25×/s forever — that idle
        # repaint held the GIL and stole time from the audio/response threads.
        if not (self._hovering or self._drag_over):
            return
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path = pick_file(self)
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.PRI, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

        p.end()

    def _paint_idle(self, p, W, H, hover):
        # One line: upload glyph, then the invitation. The zone used to be a
        # 100 px box that mostly showed empty space.
        cy = H / 2
        ax = 26
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(ax, cy - 7), QPointF(ax, cy + 4))
        p.drawLine(QPointF(ax - 5, cy - 2), QPointF(ax, cy - 7))
        p.drawLine(QPointF(ax + 5, cy - 2), QPointF(ax, cy - 7))
        p.drawLine(QPointF(ax - 8, cy + 7), QPointF(ax + 8, cy + 7))
        f = QFont(FONT_UI, 9, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(f)
        p.setPen(QPen(qcol(C.TEXT if hover else C.TEXT_MED), 1))
        p.drawText(QRectF(ax + 18, 0, W - ax - 24, H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "DROP A FILE  ·  OR CLICK TO BROWSE")

    def _paint_drag_over(self, p, W, H):
        f = QFont(FONT_UI, 10, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(f)
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "⬇  RELEASE TO LOAD")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 8, 40
        p.setFont(QFont("Segoe UI Emoji", 15) if _OS == "Windows" else QFont("Arial", 15))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont(FONT_UI, 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, 7, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont(FONT_MONO, 8))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, 24, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Rajdhani", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Rajdhani", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Rajdhani", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s
