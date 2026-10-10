"""HudCanvas: the central HUD — centrepiece, status line, waveform and the overlays drawn on top."""
from __future__ import annotations

import math
import random
import time
from PyQt6.QtCore import QLineF, QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen,
    QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget
from collections import deque

from .base import (
    C, HoloAvatar, _sfx, qcol,
)
from .metrics import (
    _metrics,
)

class HudCanvas(QWidget):
    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        # Centrepieces are built on first use (see _centrepiece): the legacy
        # face's mesh alone costs ~60 ms, which nobody using the sphere should
        # pay at startup. Once built they are kept, so switching is instant.
        # If one cannot be built the reactor core is drawn instead, so the
        # panel is never empty.
        self._avatar = None
        self._sphere = None
        self._built: set[str] = set()

        # Which centrepiece to draw. Read once here and changed live by the
        # settings toggle.
        try:
            from memory.config_manager import get_hud_style
            self.hud_style = get_hud_style()
        except Exception:
            self.hud_style = "sphere"
        self._core_phase = 0.0

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._step_t     = time.time()
        self._blink      = True
        self._blink_tick = 0

        # Rescaled-face cache: the smooth rescale is expensive, so we keep the
        # last result and only rebuild it when the (quantised) size changes.

        # Static grid-dot layer, pre-rendered once per size/theme into a pixmap
        # so paintEvent blits it in one call instead of thousands of drawPoint()s.
        self._grid_cache: QPixmap | None = None
        self._grid_key = None
        # Repaint throttle counter (idle frames drop to ~20 Hz — see _step()).
        self._paint_tick = 0

        # Live audio reactivity: _live_amp is written from the audio threads
        # (0.0–1.0), _amp_disp is the smoothed value the paint code reads.
        self._live_amp  = 0.0
        self._amp_disp  = 0.0
        # (frames, start_time, hop) posted by the playback thread — see
        # push_visemes(). None means "no schedule; use the plain level".
        self._visemes = None
        self._vis_i = None        # first schedule frame not yet handed to the mouth
        self._base_scale = 1.0    # slow "breathing" target; amp is added per-frame
        self._base_halo  = 55.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

        # Boot sequence: started by the main window (see _start_boot).
        self._boot_t0: float | None = None

        # Telemetry strip: a rolling history of (cpu, mem) sampled from the
        # shared _metrics poller, so the HUD adds no probes of its own.
        self._tele_hist: deque = deque(maxlen=48)
        self._tele_t = 0.0
        self._session_t0 = time.time()

        # Diagnostics gauges: (items, start_time) set by show_diagnostics().
        self._diag = None

        # Pre-drawn static layers, one slot per name — see _blit_static().
        self._static_cache: dict = {}

    def _centrepiece(self):
        """The object for the current style, building it on first use.
        Returns None for the reactor core (drawn inline) or on failure."""
        style = self.hud_style
        if style == "face":
            if "face" not in self._built:
                self._built.add("face")
                try:
                    self._avatar = HoloAvatar() if HoloAvatar is not None else None
                except Exception:
                    self._avatar = None
            return self._avatar
        if style == "sphere":
            if "sphere" not in self._built:
                self._built.add("sphere")
                try:
                    from core.holosphere import HoloSphere
                    self._sphere = HoloSphere()
                except Exception as e:
                    print(f"[HUD] Holo-Sphere unavailable, using reactor core: {e}")
                    self._sphere = None
            return self._sphere
        return None

    def _state_colours(self) -> tuple[QColor, QColor]:
        """(main, accent) for the centrepiece — one colour language for every
        style: blue idle, green listening, gold thinking, bright on speech."""
        if self.muted:
            return qcol(C.MUTED_C), qcol(C.MUTED_C)
        main = qcol(C.PRI)
        if self.speaking:
            return main, qcol(C.ACC if self.hud_style == "face" else C.PRI)
        if self.state in ("THINKING", "PROCESSING"):
            return main, qcol(C.ACC2)
        if self.state == "LISTENING":
            return main, qcol(C.GREEN)
        return main, qcol(C.PRI)

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Ask the avatar to look somewhere for a moment (see HoloAvatar.glance)."""
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            pass

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Thread-safe: hand over a schedule of (level, openness, width) frames.

        The playback thread writes up to 200 ms of audio in one go, so a single
        averaged level would only move the mouth five times a second — enough to
        flap, nowhere near enough to articulate. It instead posts the whole
        slice's worth of 20 ms frames here and `_step()` plays them out against
        the wall clock, in step with the audio going to the speakers.

        `at` is the wall-clock time this batch will *begin to sound*, which the
        caller tracks as a playback cursor. It is not the time of the call, and
        the difference is the whole point: `stream.write` returns once the buffer
        accepts the samples, so consecutive batches are handed over far faster
        than they play. Anchoring each one to "now" made every batch start while
        its predecessor was still sounding, so each schedule replaced the last
        after a couple of frames and the mouth only ever played the opening
        instant of every 200 ms — the reason it did not match the words.

        Successive batches are therefore *appended* into one continuous
        timeline, not swapped in. A paragraph is one schedule; the mouth stops
        falling into a gap at every chunk boundary and having to climb back out.
        """
        try:
            if not frames:
                return
            hop = max(1e-3, float(hop))
            at = float(at)
            new = list(frames)
            cur = self._visemes
            if cur is not None:
                old, t0, ohop = cur
                if abs(ohop - hop) < 1e-6:
                    # Where in the existing timeline does this batch land?
                    i = int(round((at - t0) / hop))
                    if 0 <= i <= len(old) + 1:
                        # Continues (or slightly overlaps) what is already
                        # queued: extend rather than restart. Drop whatever has
                        # already been played so the list cannot grow without
                        # bound over a long reply.
                        merged = old[:i] + new
                        played = int((time.time() - t0) / hop) - 2
                        if played > 60:
                            merged = merged[played:]
                            t0 += played * hop
                            if self._vis_i is not None:
                                self._vis_i = max(0, self._vis_i - played)
                        self._visemes = (merged, t0, hop)
                        return
            self._visemes = (new, at, hop)
            self._vis_i = None
        except Exception:
            pass

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the audio threads. Stores the louder of
        the incoming level and the current value so brief gaps between chunks
        don't make the waveform stutter; _step() decays it back down."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            return
        if lv < 0.0:
            lv = 0.0
        elif lv > 1.0:
            lv = 1.0
        if lv > self._live_amp:
            self._live_amp = lv

    def _make_grid(self, W: int, H: int) -> QPixmap:
        """Pre-render the static grid-dot background into a transparent pixmap so
        paintEvent can blit it once per frame instead of running a nested
        drawPoint() loop across the whole widget every 16 ms."""
        # Hex lattice + vignette, drawn once per size/theme. The lattice is
        # barely there on purpose: texture that says "instrument", never a
        # pattern the eye has to read past to reach the centrepiece.
        pm = QPixmap(max(1, W), max(1, H))
        pm.fill(Qt.GlobalColor.transparent)
        gp = QPainter(pm)
        gp.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = 22.0                                   # hex radius
        hw, vh = math.sqrt(3) * s, 1.5 * s
        lines = []
        row = 0
        y = -s
        while y < H + s:
            x0 = -hw if row % 2 == 0 else -hw / 2
            x = x0
            while x < W + hw:
                pts = [QPointF(x + s * math.cos(math.radians(60 * k + 30)),
                               y + s * math.sin(math.radians(60 * k + 30))) for k in range(6)]
                for k in range(3):                 # 3 edges per hex covers the lattice
                    lines.append(QLineF(pts[k], pts[k + 1]))
                x += hw
            y += vh
            row += 1
        lattice = qcol(C.PRI)
        lattice.setAlpha(14)
        gp.setPen(QPen(lattice, 1))
        gp.drawLines(lines)

        g = QRadialGradient(W / 2, H * 0.45, max(W, H) * 0.75)
        edge = qcol(C.BG)
        clear = qcol(C.BG); clear.setAlpha(0)
        mid = qcol(C.BG); mid.setAlpha(120)
        edge.setAlpha(235)
        g.setColorAt(0.0, clear)
        g.setColorAt(0.55, mid)
        g.setColorAt(1.0, edge)
        gp.setPen(Qt.PenStyle.NoPen)
        gp.setBrush(QBrush(g))
        gp.drawRect(0, 0, W, H)
        gp.end()
        return pm

    def _step(self):
        self._tick += 1
        now = time.time()

        # ── Live audio reactivity ────────────────────────────────────────────
        # A viseme schedule, if one is playing, gives both the level and the
        # mouth shape for this exact instant; otherwise fall back to the peak
        # level the audio threads pushed in.
        v_open = v_wide = v_level = None
        v_seq = None
        sched = self._visemes
        if sched is not None:
            frames, t0, hop = sched
            i = int((now - t0) / hop)
            if 0 <= i < len(frames):
                # Hand over *every* frame since the last tick, not just the one
                # under the cursor. This timer runs at 60 Hz but the paint is
                # throttled and the machine may be busy, so a tick can span two
                # or three 20 ms frames — and a consonant closure is only two
                # frames long. Sampling one and discarding the rest is how the
                # closures between words went missing.
                j = self._vis_i if self._vis_i is not None else i
                v_seq = frames[max(0, j):i + 1]
                self._vis_i = max(j, i + 1)
                v_level, v_open, v_wide = frames[i]
                if v_seq:
                    peak = max(f[0] for f in v_seq)
                    if peak > self._live_amp:
                        self._live_amp = peak
            elif i >= len(frames):
                self._visemes = None        # schedule spent
                self._vis_i = None

        # Audio threads push peaks into _live_amp; decay it toward silence so
        # gaps between chunks fade out instead of freezing, then smooth it.
        self._live_amp *= 0.86
        self._amp_disp += (self._live_amp - self._amp_disp) * 0.45
        amp = self._amp_disp

        # The avatar animates off the very same smoothed level the waveform
        # uses — one audio source, so the mouth can never drift out of sync.
        dt = now - self._step_t
        self._step_t = now
        # Integrated, not derived from absolute time: multiplying wall-clock by
        # a rate that changes with state jumps the rings the instant JARVIS
        # starts talking. Same lesson the head's sway taught.
        self._core_phase += min(0.10, max(0.0, dt))

        piece = self._centrepiece()
        if piece is not None and self.hud_style == "sphere":
            piece.step(dt, amp, self.state, self.speaking, self.muted)
        elif piece is not None and self.hud_style == "face":
            self._avatar.step(dt, amp, speaking=self.speaking,
                              muted=self.muted, state=self.state,
                              v_open=v_open, v_wide=v_wide or 0.0,
                              v_level=v_level, v_seq=v_seq,
                              v_hop=(sched[2] if sched is not None else 0.02))
        else:
            # Fallback core: slow "breathing" base target, lifted by the level.
            if now - self._last_t > (0.12 if self.speaking else 0.5):
                if self.speaking:
                    self._base_scale = 1.03
                    self._base_halo  = 122.0
                elif self.muted:
                    self._base_scale = random.uniform(0.998, 1.002)
                    self._base_halo  = random.uniform(15, 28)
                else:
                    self._base_scale = random.uniform(1.001, 1.008)
                    self._base_halo  = random.uniform(48, 68)
                self._last_t = now

            if self.muted:
                self._tgt_scale, self._tgt_halo = self._base_scale, self._base_halo
            elif self.speaking:
                self._tgt_scale = self._base_scale + amp * 0.13
                self._tgt_halo  = self._base_halo  + amp * 95.0
            else:
                self._tgt_scale = self._base_scale + amp * 0.06
                self._tgt_halo  = self._base_halo  + amp * 75.0

            sp = 0.38 if self.speaking else (0.30 if amp > 0.02 else 0.15)
            self._scale += (self._tgt_scale - self._scale) * sp
            self._halo  += (self._tgt_halo  - self._halo)  * sp

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
            _blinked = True
        else:
            _blinked = False

        # Repaint throttling — advancing the animation state above is cheap at
        # 60 Hz, but the paint is heavy. Active (speaking, audio, thinking) runs
        # at ~30 Hz, which is the frame rate animation has used for talking
        # characters forever and is indistinguishable here; idle drops to ~20 Hz
        # so a sleeping HUD stops pinning a CPU core. The visuals stay smooth
        # either way because the animation state keeps stepping at 60 Hz.
        self._paint_tick = (self._paint_tick + 1) % 60   # divisible by 2, 3, 5, 6
        if now - self._tele_t >= 2.0:
            self._tele_t = now
            try:
                s = _metrics.snapshot()
                self._tele_hist.append((float(s["cpu"]), float(s["mem"])))
            except Exception:
                pass

        active = (self.speaking or amp > 0.02 or self._boot_t0 is not None
                  or self._diag is not None
                  or self.state in ("THINKING", "PROCESSING"))
        # Idle repaint rate per style (the 60 Hz step timer divided by this):
        # the face needs ~20 Hz for blinks and saccades to read as motion; the
        # sphere's idle spin is ~1.2° per frame at 12 Hz, which reads smooth;
        # the reactor drifts slowly enough for 10 Hz.
        idle_div = {"face": 3, "sphere": 5}.get(self.hud_style, 6)
        if _blinked or (self._paint_tick % 2 == 0 if active
                        else self._paint_tick % idle_div == 0):
            # Nothing is on screen when the window is hidden or minimised, so
            # rendering the avatar into it is pure waste — and this app is meant
            # to sit running all day. The animation state above keeps stepping,
            # so it picks up mid-motion instead of snapping when you come back.
            if self._on_screen():
                self.update()

    def _on_screen(self) -> bool:
        """True only when this canvas can actually be seen by the user."""
        try:
            if not self.isVisible():
                return False
            win = self.window()
            return not (win.isMinimized() or win.isHidden())
        except Exception:
            return True      # never let a visibility check stop the HUD drawing

    # ── reactor core ─────────────────────────────────────────────────────────
    # The centrepiece for anyone who did not want a face looking back at them.
    # Built from the same budget as the head — software QPainter, no GPU — and
    # from the same principle: everything on it means something. The rings turn
    # at a rate the state sets, the spectrum ring is the real audio level, and
    # the core brightens with the voice. Nothing here is decoration that moves
    # for its own sake, which is what made the old glowing orb feel dead.

    def _core_colours(self):
        if self.muted:
            return qcol(C.MUTED_C), qcol(C.MUTED_C)
        if self.speaking:
            return qcol(C.PRI), qcol(C.ACC)
        if self.state in ("THINKING", "PROCESSING"):
            return qcol(C.PRI), qcol(C.ACC2)
        if self.state == "LISTENING":
            return qcol(C.PRI), qcol(C.GREEN)
        return qcol(C.PRI), qcol(C.PRI_DIM)

    def _paint_core(self, p: QPainter, cx: float, cy: float, r: float,
                    W: float = 0.0, H: float = 0.0):
        """Draw the reactor at (cx, cy) with outer radius r, using the whole
        canvas (W x H) for the marks that frame it."""
        main, acc = self._core_colours()
        bg = qcol(C.BG)
        amp = self._amp_disp
        t = self._core_phase
        live = (self.speaking or amp > 0.04) and not self.muted

        def blend(col: QColor, a: float) -> QColor:
            """Pre-mix onto the background instead of asking Qt to composite.
            The raster engine's opaque path is several times faster than its
            translucent one, and everything here is a line or an arc."""
            k = max(0.0, min(1.0, a))
            return QColor(int(bg.red()   + (col.red()   - bg.red())   * k),
                          int(bg.green() + (col.green() - bg.green()) * k),
                          int(bg.blue()  + (col.blue()  - bg.blue())  * k))

        p.setBrush(Qt.BrushStyle.NoBrush)

        # 1. The atmosphere. One radial gradient doing what a stack of discs did
        #    badly: a wide, soft body of light that gives the thing presence
        #    before any detail is read. This single element decides whether the
        #    HUD looks vast or looks small, so it is drawn first and drawn big.
        # Concentrated rather than spread: a gradient reaching the outer rim
        # washes the whole disc a flat dim blue and reads as fog. Ending it at
        # two thirds leaves it a body of light with somewhere to fall off to,
        # which is what makes it look lit rather than tinted.
        lift = 1.0 + 0.55 * amp + (0.18 if self.speaking else 0.0)
        p.setPen(Qt.PenStyle.NoPen)
        for gr, a0, a1 in ((r * 0.70, 0.30, 0.0), (r * 0.34, 0.34, 0.0)):
            g = QRadialGradient(cx, cy, gr)
            g.setColorAt(0.00, blend(main, min(0.95, a0 * lift)))
            g.setColorAt(0.45, blend(main, min(0.95, a0 * lift * 0.52)))
            g.setColorAt(0.78, blend(main, min(0.95, a0 * lift * 0.18)))
            g.setColorAt(1.00, blend(main, a1))
            p.setBrush(QBrush(g))
            p.drawEllipse(QRectF(cx - gr, cy - gr, gr * 2, gr * 2))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 2–5. The static frame — corner marks, crosshair, outer circles and
        #      graduations. None of it moves, so it is drawn once into a
        #      transparent layer and blitted; rebuilt only when the size or
        #      the state colour changes.
        def static_layer(q: QPainter):
            # 2. Frame marks at the corners of the whole canvas, not of the
            #    circle. They are what set the scale: the eye reads the
            #    reactor as filling the room rather than sitting in it.
            if W > 40 and H > 40:
                m, arm = min(W, H) * 0.035, min(W, H) * 0.055
                q.setPen(QPen(blend(main, 0.45), 1.4))
                for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                    x = cx + sx * (W / 2 - m)
                    y = cy + sy * (H / 2 - m)
                    q.drawLine(QLineF(x, y, x - sx * arm, y))
                    q.drawLine(QLineF(x, y, x, y - sy * arm))

            # 3. Crosshair across the full canvas, broken around the core so
            #    it frames the reactor rather than crossing it.
            q.setPen(QPen(blend(main, 0.16), 1))
            gap = r * 0.62
            if W > 40:
                q.drawLine(QLineF(cx - W / 2, cy, cx - gap, cy))
                q.drawLine(QLineF(cx + gap, cy, cx + W / 2, cy))
            if H > 40:
                q.drawLine(QLineF(cx, cy - H / 2, cx, cy - gap))
                q.drawLine(QLineF(cx, cy + gap, cx, cy + H / 2))

            # 4. Two thin outer circles. Sparse on purpose — a dense ring
            #    reads as a grey band at this size.
            for rr, a in ((1.00, 0.34), (0.93, 0.16)):
                rad = r * rr
                q.setPen(QPen(blend(main, a), 1))
                q.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

            # 5. Long, sparse graduations: 24 majors reaching well in from
            #    the rim, with shorter minors between them.
            major, minor = [], []
            for i in range(72):
                a = math.radians(i * 5.0)
                ca, sa = math.cos(a), math.sin(a)
                if i % 3 == 0:
                    major.append(QLineF(cx + ca * r * 0.885, cy + sa * r * 0.885,
                                        cx + ca * r * 0.985, cy + sa * r * 0.985))
                else:
                    minor.append(QLineF(cx + ca * r * 0.945, cy + sa * r * 0.945,
                                        cx + ca * r * 0.985, cy + sa * r * 0.985))
            q.setPen(QPen(blend(main, 0.42), 1.3))
            q.drawLines(major)
            q.setPen(QPen(blend(main, 0.18), 1))
            q.drawLines(minor)

        self._blit_static(p, ("core", W, H, cx, cy, r, main.rgb(), bg.rgb()), static_layer)

        # 6. Sweeping arcs. Long spans, not dashes — the original's grandeur
        #    came from a few big strokes. Speed is the state: idle drifts,
        #    thinking hurries, speaking runs.
        rate = 1.0 + (1.9 if self.state in ("THINKING", "PROCESSING") else 0.0) \
                   + (1.2 if self.speaking else 0.0)
        for k, (rr, span, count, dirn, col, a, wid) in enumerate((
                (0.955, 118, 2, +1, acc,  0.75, 2.0),
                (0.845, 82,  3, -1, main, 0.38, 1.3),
                (0.760, 150, 1, +1, acc,  0.45, 1.6),
                (0.660, 64,  4, -1, main, 0.26, 1.1),
                (0.545, 128, 2, +1, main, 0.30, 1.2))):
            rad = r * rr
            p.setPen(QPen(blend(col, a), wid))
            box = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            base = (t * rate * (9 + k * 6) * dirn) % 360.0
            for sgm in range(count):
                p.drawArc(box, int((base + sgm * (360.0 / count)) * 16),
                          int(span * 16))

        # 7. The voice, as a ring of graduations that grow with it. Kept out at
        #    a wide radius so it never crowds the middle.
        n = 60
        ring = r * 0.415
        spikes = []
        for i in range(n):
            a = math.radians(i * (360.0 / n))
            ca, sa = math.cos(a), math.sin(a)
            wob = 0.5 + 0.5 * math.sin(t * 2.3 + i * 0.42)
            idle = 0.018 + 0.012 * math.sin(t * 1.2 + i * 0.7)
            h = r * (idle + (amp * 0.20 * wob if live else 0.0))
            spikes.append(QLineF(cx + ca * ring, cy + sa * ring,
                                 cx + ca * (ring + h), cy + sa * (ring + h)))
        p.setPen(QPen(blend(acc if live else main, 0.25 + 0.5 * amp), 1.6))
        p.drawLines(spikes)

        # 8. The inner ring the name sits in.
        inner = r * 0.355
        p.setPen(QPen(blend(acc, 0.30 + 0.45 * amp), 1.5))
        p.drawEllipse(QRectF(cx - inner, cy - inner, inner * 2, inner * 2))

        # 9. The name, sized from the string rather than from the radius alone:
        #    "J.A.R.V.I.S" and a name someone renamed to "MAX" are very
        #    different widths, and a fixed fraction of r spills one of them past
        #    the ring it is supposed to sit inside.
        name = self._assistant_name or ""
        if name:
            space = max(1.0, r * 0.018)
            fsz = max(8, int(min(r * 0.105,
                                 (inner * 1.75) / max(1, len(name)) * 1.6 - space)))
            f = QFont("Rajdhani", fsz, QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, space)
            p.setFont(f)
            p.setPen(QPen(blend(qcol(C.WHITE), 0.6 + 0.4 * min(1.0, amp * 2)), 1))
            p.drawText(QRectF(cx - r, cy - fsz, r * 2, fsz * 2),
                       Qt.AlignmentFlag.AlignCenter, name)

    def _blit_static(self, p: QPainter, key: tuple, draw) -> None:
        """Draw `draw(painter)` once into a transparent, canvas-sized layer and
        blit it on later frames. One slot per layer name (key[0]), so the
        cache can never grow: a new size or colour simply replaces it."""
        slot = self._static_cache.get(key[0])
        if slot is None or slot[0] != key:
            dpr = self.devicePixelRatioF()
            pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setBrush(Qt.BrushStyle.NoBrush)
            draw(q)
            q.end()
            slot = (key, pm)
            self._static_cache[key[0]] = slot
        p.drawPixmap(0, 0, slot[1])

    def _paint_face_rings(self, p: QPainter, cx: float, cy: float, r: float,
                          main: QColor, acc: QColor) -> None:
        """Arc-reactor rings behind the head — the reactor style's language,
        pared down so the face stays the subject. Speed is the state, exactly
        as on the reactor: idle drifts, thinking hurries, speaking runs."""
        bg = qcol(C.BG)
        amp = self._amp_disp
        t = self._core_phase

        def blend(col: QColor, a: float) -> QColor:
            k = max(0.0, min(1.0, a))
            return QColor(int(bg.red()   + (col.red()   - bg.red())   * k),
                          int(bg.green() + (col.green() - bg.green()) * k),
                          int(bg.blue()  + (col.blue()  - bg.blue())  * k))

        p.setBrush(Qt.BrushStyle.NoBrush)
        R = r * 1.18                                      # just clear of the cheeks

        # Thin full circle + graduations: the static frame, cached.
        def static_layer(q: QPainter):
            q.setPen(QPen(blend(main, 0.20), 1))
            q.drawEllipse(QRectF(cx - R, cy - R, R * 2, R * 2))
            ticks = []
            for i in range(48):
                a = math.radians(i * 7.5)
                ca, sa = math.cos(a), math.sin(a)
                l0 = R * (0.955 if i % 4 == 0 else 0.975)
                ticks.append(QLineF(cx + ca * l0, cy + sa * l0, cx + ca * R, cy + sa * R))
            q.setPen(QPen(blend(main, 0.28), 1))
            q.drawLines(ticks)

        self._blit_static(p, ("rings", self.width(), self.height(), cx, cy, R,
                              main.rgb(), bg.rgb()), static_layer)

        # Rotating arcs, two directions.
        rate = (1.0 + (1.9 if self.state in ("THINKING", "PROCESSING") else 0.0)
                    + (1.2 if self.speaking else 0.0))
        if self.muted or self.state == "SLEEPING":
            rate = 0.25
        for k, (rr, span, count, dirn, col, a, wid) in enumerate((
                (1.07, 100, 2, +1, acc,  0.55 + 0.35 * amp, 1.8),
                (0.90, 60,  3, -1, main, 0.30, 1.2),
                (1.14, 34,  4, -1, main, 0.22, 1.0))):
            rad = R * rr
            p.setPen(QPen(blend(col, a), wid))
            box = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            base = (t * rate * (10 + k * 7) * dirn) % 360.0
            for sgm in range(count):
                p.drawArc(box, int((base + sgm * (360.0 / count)) * 16), int(span * 16))

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():      # device not ready (e.g. 0-size during layout) — skip cleanly
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots — blitted from a cached layer; rebuilt only when the size
        # or the theme's ghost colour changes (so live re-theming still works).
        _gkey = (W, H, C.PRI_GHO)
        if self._grid_cache is None or self._grid_key != _gkey:
            self._grid_cache = self._make_grid(W, H)
            self._grid_key   = _gkey
        p.drawPixmap(0, 0, self._grid_cache)

        # ── holographic head ────────────────────────────────────────────────
        # Sized to the band between the top of the canvas and the status line,
        # capped by width, so it fills the HUD at any window size — including
        # fullscreen — without ever colliding with the status text below.
        _sy_status = cy + fw * 0.40
        piece = self._centrepiece()
        if piece is not None and self.hud_style == "sphere":
            # Holo-Sphere: centred in the band above the status line, sized
            # so its orbit rings (1.44r) and outer HUD ring stay on canvas.
            _band_t = 12.0
            _band_h = max(60.0, _sy_status - 12.0 - _band_t)
            _r = min(W * 0.30, _band_h / 2.0 / 1.32)
            _scy = _band_t + _band_h / 2.0
            _main, _acc = self._state_colours()
            self._paint_face_rings(p, cx, _scy, _r * 1.08, _main, _acc)
            piece.paint(p, cx, _scy, _r, _main, _acc, qcol(C.BG))

        elif piece is not None and self.hud_style == "face":
            _band_t = 12.0
            _band_h = max(60.0, _sy_status - 12.0 - _band_t)
            _r_head = min(fw * 0.355, _band_h / (self._avatar.SPAN + 0.08))
            _head_cy = _band_t + (_band_h - self._avatar.SPAN * _r_head) / 2.0 + _r_head
            _main, _acc = self._state_colours()
            self._paint_face_rings(p, cx, _head_cy, _r_head, _main, _acc)
            self._avatar.paint(p, cx, _head_cy, _r_head, _main, _acc, qcol(C.BG))

        # reactor core — the other centrepiece, and the fallback if the head
        # could not be built. There is no third path: the old face.png branch
        # was unreachable (no such file ships) and the bare orb it fell through
        # to is what this replaces.
        else:
            _band_t = 12.0
            _band_h = max(60.0, _sy_status - 12.0 - _band_t)
            _r = min(W * 0.46, _band_h / 2.0)
            self._paint_core(p, cx, _band_t + _band_h / 2.0, _r, W, _band_h)

        # status text
        sy = _sy_status
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Rajdhani", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform — reacts to the real audio level (mic while listening,
        # JARVIS's own voice while speaking). Falls back to a gentle idle
        # ripple when there's no sound. _amp_disp is the smoothed 0–1 level.
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        amp = self._amp_disp
        mid = (N - 1) / 2.0
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            else:
                env     = (1.0 - abs(i - mid) / mid) ** 0.7      # center-weighted hump
                shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                idle    = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                hgt     = int(max(2, min(24, idle + amp * 22.0 * env * shimmer)))
                if amp > 0.05:
                    cl = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
                else:
                    cl = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

        self._paint_telemetry(p, W)
        if self._diag is not None:
            self._paint_diag(p, W, _sy_status, fw)
        if self._boot_t0 is not None:
            self._paint_boot(p, W, H, cx, cy, fw)

        p.end()   # end deterministically so the backing store never flushes an active painter

    # ── telemetry strip ──────────────────────────────────────────────────────
    # Two small sparklines in the top corners and a session clock: the
    # control-room texture of the films, built only from numbers the side
    # panel already polls, so it shows nothing that is not real.

    def _paint_telemetry(self, p: QPainter, W: float) -> None:
        if W < 260:
            return
        hist = list(self._tele_hist)
        sw, sh, m = min(96.0, W * 0.2), 18.0, 12.0
        f = QFont("Rajdhani", 8, QFont.Weight.Bold)
        p.setFont(f)
        for idx, (label, x, colname) in enumerate((("CPU", m, C.PRI),
                                                   ("MEM", W - m - sw, C.ACC2))):
            vals = [h[idx] for h in hist]
            cur = vals[-1] if vals else 0.0
            c = qcol(colname)
            dim = qcol(C.TEXT_DIM)
            p.setPen(QPen(dim, 1))
            p.drawText(QRectF(x, 6, sw, 12), Qt.AlignmentFlag.AlignLeft, label)
            p.setPen(QPen(c, 1))
            p.drawText(QRectF(x, 6, sw, 12), Qt.AlignmentFlag.AlignRight, f"{cur:4.0f}%")
            y0 = 20.0
            p.setPen(QPen(qcol(C.BORDER_B), 1))
            p.drawLine(QLineF(x, y0 + sh, x + sw, y0 + sh))
            if len(vals) >= 2:
                n = self._tele_hist.maxlen or len(vals)
                step = sw / max(1, n - 1)
                x_start = x + sw - step * (len(vals) - 1)
                pts = [QPointF(x_start + i * step, y0 + sh - sh * min(v, 100.0) / 100.0)
                       for i, v in enumerate(vals)]
                p.setPen(QPen(c, 1.2))
                p.drawPolyline(pts)

        el = int(time.time() - self._session_t0)
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(m, 42, sw * 1.4, 12), Qt.AlignmentFlag.AlignLeft,
                   f"T+{el // 3600:02d}:{el % 3600 // 60:02d}:{el % 60:02d}")

    # ── diagnostics gauges ───────────────────────────────────────────────────
    # Filled by plugins/diagnostics.py through JarvisUI.show_diagnostics: a row
    # of ring gauges that sweep up to their reading, hold, then fade. The text
    # readout still goes to the content panel; this is the at-a-glance view.

    _DIAG_SECS = 14.0

    def show_diagnostics(self, items: list) -> None:
        """items: [(label, percent or None, warn_threshold, invert), ...].
        A single attribute assignment, so it is safe from a worker thread;
        the paint timer picks it up on its next frame."""
        self._diag = (list(items)[:5], time.time())

    def _paint_diag(self, p: QPainter, W: float, sy_status: float, fw: float) -> None:
        items, t0 = self._diag
        t = time.time() - t0
        if t >= self._DIAG_SECS or not items:
            self._diag = None
            return
        fade = min(1.0, t / 0.3, (self._DIAG_SECS - t) / 0.8)
        sweep = 1 - (1 - min(1.0, t / 1.2)) ** 3          # ease-out

        def col(base: str, a: float = 1.0) -> QColor:
            c = qcol(base)
            c.setAlpha(int(255 * max(0.0, min(1.0, a * fade))))
            return c

        n = len(items)
        r = min(W / (n * 2.6), fw * 0.075, 40.0)
        gap = r * 2.6
        y = sy_status - r * 1.9
        x0 = W / 2 - gap * (n - 1) / 2

        plate = QRectF(x0 - gap / 2, y - r * 1.45, gap * n, r * 3.15)
        p.setPen(QPen(col(C.PRI, 0.45), 1))
        p.setBrush(QBrush(col(C.BG, 0.85)))
        p.drawRoundedRect(plate, 6, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)

        vf = QFont("Rajdhani", max(7, int(r * 0.36)), QFont.Weight.Bold)
        lf = QFont("Rajdhani", max(6, int(r * 0.26)), QFont.Weight.Bold)
        for i, (label, pct, warn, invert) in enumerate(items):
            cx = x0 + i * gap
            box = QRectF(cx - r, y - r, r * 2, r * 2)
            p.setPen(QPen(col(C.BORDER_B), max(2.0, r * 0.12)))
            p.drawArc(box, 225 * 16, -270 * 16)
            if pct is None:
                val_txt, ccol = "—", C.TEXT_DIM
            else:
                bad = pct <= warn if invert else pct >= warn
                ccol = C.RED if bad else (C.ACC2 if (not invert and pct >= warn * 0.8) else C.GREEN)
                val_txt = f"{pct * sweep:.0f}%"
                pen = QPen(col(ccol), max(2.0, r * 0.12))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(box, 225 * 16, int(-270 * 16 * min(pct, 100.0) / 100.0 * sweep))
            p.setFont(vf)
            p.setPen(QPen(col(C.WHITE, 0.9), 1))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, val_txt)
            p.setFont(lf)
            p.setPen(QPen(col(ccol), 1))
            p.drawText(QRectF(cx - r * 1.3, y + r * 0.78, r * 2.6, r * 0.6),
                       Qt.AlignmentFlag.AlignCenter, label)

    # ── boot sequence ────────────────────────────────────────────────────────
    # A short "systems coming online" pass drawn over the HUD at launch: a veil
    # that lifts, a scan ring and scan line, and a checklist that ticks itself
    # off. Timed against the boot tone in core/sfx.py so sound and picture land
    # together. Purely cosmetic and self-terminating.

    _BOOT_SECS  = 3.0
    _BOOT_LINES = ("CORE PROCESSOR", "AUDIO SUBSYSTEM", "VISUAL CORTEX",
                   "NEURAL LINK", "PROTOCOL ENGINE")

    def _start_boot(self) -> None:
        self._boot_t0 = time.time()
        if _sfx is not None:
            _sfx.play("boot")

    def _paint_boot(self, p: QPainter, W: float, H: float,
                    cx: float, cy: float, fw: float) -> None:
        t = time.time() - self._boot_t0
        if t >= self._BOOT_SECS:
            self._boot_t0 = None
            return

        def col(base: str, a: float) -> QColor:
            c = qcol(base)
            c.setAlpha(int(255 * max(0.0, min(1.0, a))))
            return c

        # Everything fades together over the last 0.6 s.
        fade = min(1.0, (self._BOOT_SECS - t) / 0.6)

        # 1. The veil: opaque at first, lifting as systems come up.
        veil = 1.0 if t < 0.5 else max(0.0, 1.0 - (t - 0.5) / 1.9)
        p.fillRect(QRectF(0, 0, W, H), col(C.BG, veil * 0.92 * fade))

        # 2. Scan ring expanding from the centre, with a trailing echo.
        p.setBrush(Qt.BrushStyle.NoBrush)
        rmax = math.hypot(W, H) / 2
        for lag, a in ((0.0, 0.85), (0.18, 0.35)):
            k = max(0.0, min(1.0, (t - lag) / 1.1))
            if 0.0 < k < 1.0:
                rr = rmax * (1 - (1 - k) ** 3)
                p.setPen(QPen(col(C.PRI, a * (1 - k) * fade), 2.0))
                p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        # 3. Horizontal scan line sweeping top to bottom once.
        k = t / 1.4
        if k < 1.0:
            y = H * k
            p.fillRect(QRectF(0, y - 1, W, 2), col(C.ACC, 0.7 * fade))
            p.fillRect(QRectF(0, y - 14, W, 12), col(C.PRI, 0.08 * fade))

        # 4. The checklist, one line every 0.28 s, each flipping to ONLINE.
        fsz = max(8, int(fw * 0.026))
        f = QFont("Rajdhani", fsz, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(f)
        lh = fsz * 1.9
        x0 = cx - fsz * 12
        y0 = cy - lh * (len(self._BOOT_LINES) + 2) / 2
        # Backing plate so the checklist stays legible over the bright face.
        pad = fsz * 1.2
        plate = QRectF(x0 - pad, y0 - lh, fsz * 23 + pad * 2,
                       lh * (len(self._BOOT_LINES) + 2.4) + pad)
        p.setPen(QPen(col(C.PRI, 0.45 * fade), 1))
        p.setBrush(QBrush(col(C.BG, 0.82 * fade)))
        p.drawRoundedRect(plate, 6, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(col(C.PRI, fade), 1))
        p.drawText(QPointF(x0, y0), "INITIALISING " + (self._assistant_name or "SYSTEMS").upper())
        for i, label in enumerate(self._BOOT_LINES):
            ts = 0.35 + i * 0.28
            if t < ts:
                break
            y = y0 + lh * (i + 1.4)
            online = t > ts + 0.22
            p.setPen(QPen(col(C.WHITE, 0.75 * fade), 1))
            p.drawText(QPointF(x0, y), f"{label:<16}")
            dots = "." * min(6, int((t - ts) * 30))
            p.setPen(QPen(col(C.GREEN if online else C.ACC2, fade), 1))
            p.drawText(QPointF(x0 + fsz * 15, y), "ONLINE" if online else dots)
        t_done = 0.35 + len(self._BOOT_LINES) * 0.28 + 0.25
        if t > t_done:
            p.setPen(QPen(col(C.GREEN, fade), 1))
            p.drawText(QPointF(x0, y0 + lh * (len(self._BOOT_LINES) + 1.6)),
                       "ALL SYSTEMS NOMINAL")
