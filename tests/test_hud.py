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


def test_telemetry_with_history(hud):
    for i in range(30):
        hud._tele_hist.append((10.0 + i, 50.0))
    _render(hud)
