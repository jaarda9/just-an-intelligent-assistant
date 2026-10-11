"""Offscreen renders of the HUD canvas. They catch paint-time exceptions (which
Qt would otherwise swallow into a blank widget) and check that each overlay
actually puts pixels on screen."""
import time

import pytest

from conftest import ROOT


@pytest.fixture
def hud(qapp, monkeypatch):
    import ui.hud
    monkeypatch.setattr(ui.hud, "_sfx", None)      # silent
    h = ui.hud.HudCanvas(str(ROOT / "face.png"), "J.A.R.V.I.S")
    h.resize(520, 560)
    h.state = "LISTENING"
    yield h
    h._tmr.stop()
    h.deleteLater()


def _render(h):
    img = h.grab().toImage()
    assert not img.isNull()
    return img


def _distinct_colours(img, step=8):
    return len({img.pixel(x, y) for x in range(0, img.width(), step)
                for y in range(0, img.height(), step)})


@pytest.mark.parametrize("style", ["sphere", "ring", "core", "face"])
@pytest.mark.parametrize("state", ["LISTENING", "THINKING", "SPEAKING", "SLEEPING"])
def test_renders_every_style_and_state(hud, style, state):
    hud.hud_style = style
    hud.state = state
    hud.speaking = state == "SPEAKING"
    for _ in range(3):
        hud._step()
    assert _distinct_colours(_render(hud)) > 20


def test_boot_overlay_draws_and_ends(hud):
    base = _render(hud)
    hud._boot_t0 = time.time() - 1.9          # mid-checklist
    mid = _render(hud)
    assert mid != base
    hud._boot_t0 = time.time() - 10           # long finished
    _render(hud)
    assert hud._boot_t0 is None


def test_diagnostics_gauges_draw_and_expire(hud):
    base = _render(hud)
    hud.show_diagnostics([("CPU", 65.0, 85, False), ("GPU", None, 90, False),
                          ("RAM", 42.0, 85, False), ("BATT", 15.0, 20, True)])
    hud._diag = (hud._diag[0], time.time() - 2)
    assert _render(hud) != base
    hud._diag = (hud._diag[0], time.time() - 60)
    _render(hud)
    assert hud._diag is None


def test_deep_idle_halves_repaints_and_wakes_instantly(hud, monkeypatch):
    hud.hud_style = "sphere"
    hud._centrepiece()
    hud.state = "LISTENING"
    hud._last_state_seen = "LISTENING"
    paints = []
    monkeypatch.setattr(hud, "_on_screen", lambda: True)
    monkeypatch.setattr(hud, "update", lambda: paints.append(1))

    def count(n=120):
        paints.clear()
        for _ in range(n):
            hud._live_amp = 0.0
            hud._amp_disp = 0.0
            hud._step()
        return len(paints)
    normal = count()
    hud._last_active -= hud.DEEP_IDLE_S + 1
    deep = count()
    assert deep < normal * 0.7
    hud.state = "THINKING"                      # any activity: full rate at once
    assert count() > normal


def test_data_arcs_cpu_and_memory(hud):
    hud._cpu, hud._mem = 42.0, 95.0
    arcs = dict((side, (frac, label, col)) for side, frac, label, col in hud.data_arcs())
    assert arcs["left"][1] == "CPU 42%" and arcs["left"][2] == "PRI"
    assert arcs["right"][1] == "MEM 95%" and arcs["right"][2] == "RED"
    _render(hud)


def test_data_arc_counts_down_to_next_meeting(hud):
    import datetime as dt
    start = dt.datetime.now().astimezone() + dt.timedelta(minutes=8)
    hud.next_event = ("Board meeting - Stark Industries", start)
    side, frac, label, col = hud.data_arcs()[1]
    assert side == "right" and "min" in label and label.startswith("Board meeting")
    assert col == "WARN" and 0.8 < frac < 0.9
    hud.next_event = ("Later", start + dt.timedelta(hours=3))     # outside the hour
    assert hud.data_arcs()[1][2].startswith("MEM")
    _render(hud)
