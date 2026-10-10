"""
Protocol editor — build, edit, schedule and test protocols from the HUD
instead of editing config/protocols.json by hand.

Left: the protocols. Right: name / aliases / announcement, the steps (a tool
picked from the live tool catalogue, with a field per parameter, or a wait),
and the triggers (a time and days, or an event). Save validates through
core/protocol_store.py; Test run goes through the app's dispatcher.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QTimeEdit, QVBoxLayout, QWidget,
)

from core import protocol_store as store
from core.triggers import DAYS, describe

from .base import C, FONT_HEAD, FONT_MONO, FONT_UI


def _btn(text: str, kind: str = "dim") -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(28)
    f = QFont(FONT_UI, 9, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
    b.setFont(f)
    col = {"pri": C.PRI, "ok": C.GREEN, "bad": C.MUTED_C}.get(kind, C.TEXT_MED)
    b.setStyleSheet(f"""
        QPushButton {{ background: transparent; color: {col};
            border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 0 10px; }}
        QPushButton:hover {{ border-color: {col}; background: {C.PRI_GHO}; }}
        QPushButton:disabled {{ color: {C.BORDER_B}; border-color: {C.BORDER}; }}""")
    return b


def _label(text: str, head: bool = False) -> QLabel:
    lab = QLabel(text.upper() if head else text)
    if head:
        f = QFont(FONT_HEAD, 7, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        lab.setFont(f)
        lab.setStyleSheet(f"color: {C.PRI}; background: transparent;")
    else:
        lab.setFont(QFont(FONT_UI, 9, QFont.Weight.DemiBold))
        lab.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
    return lab


class ProtocolEditor(QWidget):
    closed = pyqtSignal()
    _OW, _OH = 820, 560

    def __init__(self, catalog: list[dict] | None, run_tool=None, parent=None):
        super().__init__(parent)
        self._catalog = {t["name"]: t for t in (catalog or store.FALLBACK_CATALOG)
                         if t["name"] not in store.FORBIDDEN_TOOLS}
        self._run_tool = run_tool
        self._current: str | None = None      # name as saved on disk
        self._steps: list[dict] = []
        self._triggers: list[dict] = []
        self.setFixedSize(self._OW, self._OH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ProtocolEditor")
        field = (f"background: {C.PANEL}; color: {C.WHITE}; border: 1px solid {C.BORDER_A};"
                 f" border-radius: 3px; padding: 3px 6px;")
        self.setStyleSheet(f"""
            QWidget#ProtocolEditor {{ background: rgba(0, 6, 10, 248);
                border: 1px solid {C.BORDER_B}; border-radius: 6px; }}
            QLineEdit, QComboBox, QTimeEdit, QDoubleSpinBox {{ {field} font-family: '{FONT_UI}'; font-size: 10pt; }}
            QListWidget {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER_A};
                border-radius: 3px; font-family: '{FONT_UI}'; font-size: 10pt; }}
            QListWidget::item {{ padding: 4px 6px; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO}; color: {C.WHITE}; }}
            QCheckBox {{ color: {C.TEXT_MED}; font-family: '{FONT_UI}'; font-size: 9pt; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        title = QLabel("PROTOCOL EDITOR")
        tf = QFont(FONT_HEAD, 11, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        title.setFont(tf)
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        root.addWidget(title)

        body = QHBoxLayout(); body.setSpacing(14)
        root.addLayout(body, stretch=1)

        # ── left: the list ─────────────────────────────────────────────────
        left = QVBoxLayout(); left.setSpacing(6)
        left.addWidget(_label("Protocols", head=True))
        self._list = QListWidget()
        self._list.setFixedWidth(180)
        self._list.currentTextChanged.connect(self._select)
        left.addWidget(self._list, stretch=1)
        row = QHBoxLayout()
        self._b_new = _btn("+ NEW", "pri"); self._b_new.clicked.connect(self._new)
        self._b_del = _btn("DELETE", "bad"); self._b_del.clicked.connect(self._delete)
        row.addWidget(self._b_new); row.addWidget(self._b_del)
        left.addLayout(row)
        body.addLayout(left)

        # ── right: the protocol ────────────────────────────────────────────
        right = QVBoxLayout(); right.setSpacing(8)
        form = QFormLayout(); form.setSpacing(6)
        self._name = QLineEdit(); self._name.setPlaceholderText("e.g. work")
        self._aliases = QLineEdit(); self._aliases.setPlaceholderText("other names, comma separated")
        self._announce = QLineEdit(); self._announce.setPlaceholderText("what JARVIS says when it runs")
        form.addRow(_label("Name"), self._name)
        form.addRow(_label("Aliases"), self._aliases)
        form.addRow(_label("Announce"), self._announce)
        right.addLayout(form)

        cols = QHBoxLayout(); cols.setSpacing(12)
        # steps
        sv = QVBoxLayout(); sv.setSpacing(5)
        sv.addWidget(_label("Steps", head=True))
        self._step_list = QListWidget()
        sv.addWidget(self._step_list, stretch=1)
        srow = QHBoxLayout()
        for text, fn in (("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1)),
                         ("REMOVE", self._remove_step)):
            b = _btn(text); b.clicked.connect(fn); srow.addWidget(b)
        sv.addLayout(srow)
        self._tool = QComboBox()
        for name, t in sorted(self._catalog.items()):
            self._tool.addItem(name, name)
        self._tool.currentIndexChanged.connect(self._rebuild_params)
        sv.addWidget(self._tool)
        self._params_box = QFormLayout(); self._params_box.setSpacing(4)
        self._param_edits: dict[str, QLineEdit] = {}
        sv.addLayout(self._params_box)
        arow = QHBoxLayout()
        b_add = _btn("+ ADD STEP", "pri"); b_add.clicked.connect(self._add_step)
        self._wait = QDoubleSpinBox(); self._wait.setRange(0.5, 30); self._wait.setValue(1.0)
        self._wait.setSuffix(" s"); self._wait.setFixedWidth(80)
        b_wait = _btn("+ WAIT"); b_wait.clicked.connect(self._add_wait)
        arow.addWidget(b_add); arow.addStretch(); arow.addWidget(self._wait); arow.addWidget(b_wait)
        sv.addLayout(arow)
        cols.addLayout(sv, stretch=3)

        # triggers
        tv = QVBoxLayout(); tv.setSpacing(5)
        tv.addWidget(_label("Triggers", head=True))
        self._trig_list = QListWidget()
        tv.addWidget(self._trig_list, stretch=1)
        b_rm_t = _btn("REMOVE TRIGGER"); b_rm_t.clicked.connect(self._remove_trigger)
        tv.addWidget(b_rm_t)
        trow = QHBoxLayout()
        self._time = QTimeEdit(); self._time.setDisplayFormat("HH:mm")
        b_time = _btn("+ AT TIME", "pri"); b_time.clicked.connect(self._add_time_trigger)
        trow.addWidget(self._time); trow.addWidget(b_time)
        tv.addLayout(trow)
        drow = QHBoxLayout(); drow.setSpacing(2)
        self._days: dict[str, QCheckBox] = {}
        for d in DAYS:
            cb = QCheckBox(d[:2].title()); cb.setChecked(d in DAYS[:5])
            self._days[d] = cb; drow.addWidget(cb)
        tv.addLayout(drow)
        erow = QHBoxLayout()
        self._event = QComboBox()
        for ev in store.EVENTS:
            self._event.addItem(describe({"on": ev}), ev)
        b_ev = _btn("+ ON EVENT", "pri"); b_ev.clicked.connect(self._add_event_trigger)
        erow.addWidget(self._event, stretch=1); erow.addWidget(b_ev)
        tv.addLayout(erow)
        cols.addLayout(tv, stretch=2)
        right.addLayout(cols, stretch=1)

        self._status = QLabel("")
        self._status.setFont(QFont(FONT_MONO, 9))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        right.addWidget(self._status)
        body.addLayout(right, stretch=1)

        bottom = QHBoxLayout()
        self._b_test = _btn("▶ TEST RUN"); self._b_test.clicked.connect(self._test)
        self._b_test.setEnabled(callable(run_tool))
        b_save = _btn("SAVE", "ok"); b_save.clicked.connect(self._save)
        b_close = _btn("CLOSE"); b_close.clicked.connect(self._close)
        bottom.addWidget(self._b_test); bottom.addStretch()
        bottom.addWidget(b_save); bottom.addWidget(b_close)
        root.addLayout(bottom)

        self._rebuild_params()
        self._reload()

    # ── list ─────────────────────────────────────────────────────────────────
    def _reload(self, select: str | None = None) -> None:
        self._protocols = store.load_all()
        self._list.blockSignals(True)
        self._list.clear()
        for name in self._protocols:
            self._list.addItem(name)
        self._list.blockSignals(False)
        target = select if select in self._protocols else next(iter(self._protocols), None)
        if target:
            self._list.setCurrentRow(list(self._protocols).index(target))
            self._select(target)
        else:
            self._new()

    def _select(self, name: str) -> None:
        if not name or name not in self._protocols:
            return
        p = self._protocols[name]
        self._current = name
        self._name.setText(name)
        self._aliases.setText(", ".join(p.get("aliases") or []))
        self._announce.setText(p.get("announce") or "")
        self._steps = [dict(s) for s in p.get("steps") or []]
        self._triggers = [dict(t) for t in p.get("triggers") or []]
        self._refresh_lists()
        self._say("")

    def _new(self) -> None:
        self._current = None
        self._list.clearSelection()
        self._name.setText(""); self._aliases.setText(""); self._announce.setText("")
        self._steps, self._triggers = [], []
        self._refresh_lists()
        self._say("New protocol — give it a name and at least one step.")
        self._name.setFocus()

    def _delete(self) -> None:
        if self._current and store.delete(self._current):
            self._say(f"Deleted '{self._current}'.")
            self._reload()

    # ── steps ────────────────────────────────────────────────────────────────
    def _rebuild_params(self) -> None:
        while self._params_box.rowCount():
            self._params_box.removeRow(0)
        self._param_edits = {}
        tool = self._catalog.get(self._tool.currentData() or "")
        if not tool:
            return
        for pname, pdesc in list((tool.get("params") or {}).items())[:4]:
            e = QLineEdit(); e.setPlaceholderText(str(pdesc)[:70])
            self._param_edits[pname] = e
            self._params_box.addRow(_label(pname), e)

    def _add_step(self) -> None:
        name = self._tool.currentData()
        if not name:
            return
        args = {k: e.text().strip() for k, e in self._param_edits.items() if e.text().strip()}
        self._steps.append({"tool": name, "args": args})
        for e in self._param_edits.values():
            e.clear()
        self._refresh_lists(select_step=len(self._steps) - 1)

    def _add_wait(self) -> None:
        self._steps.append({"wait": round(self._wait.value(), 1)})
        self._refresh_lists(select_step=len(self._steps) - 1)

    def _remove_step(self) -> None:
        i = self._step_list.currentRow()
        if 0 <= i < len(self._steps):
            del self._steps[i]
            self._refresh_lists(select_step=min(i, len(self._steps) - 1))

    def _move(self, d: int) -> None:
        i = self._step_list.currentRow()
        j = i + d
        if 0 <= i < len(self._steps) and 0 <= j < len(self._steps):
            self._steps[i], self._steps[j] = self._steps[j], self._steps[i]
            self._refresh_lists(select_step=j)

    # ── triggers ─────────────────────────────────────────────────────────────
    def _add_time_trigger(self) -> None:
        days = [d for d, cb in self._days.items() if cb.isChecked()]
        t = {"at": self._time.time().toString("HH:mm")}
        if days and len(days) < 7:
            t["days"] = days
        self._triggers.append(t)
        self._refresh_lists()

    def _add_event_trigger(self) -> None:
        ev = self._event.currentData()
        if not any(t.get("on") == ev for t in self._triggers):
            self._triggers.append({"on": ev})
        self._refresh_lists()

    def _remove_trigger(self) -> None:
        i = self._trig_list.currentRow()
        if 0 <= i < len(self._triggers):
            del self._triggers[i]
            self._refresh_lists()

    # ── save / test ──────────────────────────────────────────────────────────
    def _gather(self) -> dict:
        return {"aliases": [a for a in self._aliases.text().split(",")],
                "announce": self._announce.text(),
                "steps": self._steps, "triggers": self._triggers}

    def _save(self) -> bool:
        name = self._name.text().strip().lower()
        errs = store.save(name, self._gather(), old_name=self._current)
        if errs:
            self._say("  ".join(errs), bad=True)
            return False
        self._say(f"Saved '{name}'.", ok=True)
        self._reload(select=name)
        return True

    def _test(self) -> None:
        if not callable(self._run_tool) or not self._save():
            return
        name = self._current
        self._say(f"Running '{name}'…")

        def go():
            out = str(self._run_tool("run_protocol", {"name": name})).split(" Tell the user")[0]
            # back to the Qt thread via a single-shot timer
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._say(out, ok=not out.startswith("[GUEST")))
        threading.Thread(target=go, daemon=True, name="protocol-test").start()

    def _close(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _refresh_lists(self, select_step: int | None = None) -> None:
        self._step_list.clear()
        for i, s in enumerate(self._steps, 1):
            self._step_list.addItem(f"{i}.  {store.step_summary(s)}")
        if select_step is not None and 0 <= select_step < len(self._steps):
            self._step_list.setCurrentRow(select_step)
        self._trig_list.clear()
        for t in self._triggers:
            self._trig_list.addItem(describe(t))

    def _say(self, text: str, ok: bool = False, bad: bool = False) -> None:
        col = C.GREEN if ok else (C.MUTED_C if bad else C.TEXT_DIM)
        self._status.setStyleSheet(f"color: {col}; background: transparent;")
        self._status.setText(text)
