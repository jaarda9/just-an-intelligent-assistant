import time

import numpy as np
import pytest
from PyQt6.QtGui import QColor, QImage, QPainter


@pytest.fixture
def sphere(qapp):
    from core.holosphere import HoloSphere
    return HoloSphere()


@pytest.mark.parametrize("state,amp,speaking,muted", [
    ("IDLE", 0.0, False, False), ("LISTENING", 0.4, False, False),
    ("THINKING", 0.0, False, False), ("SPEAKING", 1.0, True, False),
    ("SLEEPING", 0.0, False, False), ("LISTENING", 0.0, False, True)])
def test_render_is_finite_and_visible(sphere, state, amp, speaking, muted):
    for _ in range(40):
        sphere.step(1 / 30, amp, state, speaking, muted)
    img = sphere.render(160, QColor("#00d4ff"), QColor("#00ff88"))
    assert not img.isNull()
    arr = sphere._last
    assert arr.dtype == np.uint8 and arr[..., 3].max() > 0


def test_boot_assembly_converges(sphere):
    from PyQt6.QtGui import QColor
    sphere.assemble = 0.0
    sphere.render(160, QColor("#00d4ff"), QColor("#00d4ff"))
    scattered = sphere._last[..., 3].astype(float)
    sphere.assemble = 1.0
    sphere.render(160, QColor("#00d4ff"), QColor("#00d4ff"))
    formed = sphere._last[..., 3].astype(float)
    # assembled: light concentrated in the middle of the image
    h, w = formed.shape
    centre = (slice(h // 4, 3 * h // 4), slice(w // 4, 3 * w // 4))
    assert formed[centre].sum() / formed.sum() > scattered[centre].sum() / max(1, scattered.sum())


def test_thinking_spins_faster_than_idle(sphere):
    for _ in range(120):
        sphere.step(1 / 30, 0, "IDLE", False, False)
    idle = sphere._spin
    for _ in range(120):
        sphere.step(1 / 30, 0, "THINKING", False, False)
    assert sphere._spin > idle * 3
    assert sphere._streams > 0.9


def test_frame_budget(sphere):
    """The whole point of the sphere: well under the face's 11.6 ms."""
    img = QImage(520, 520, QImage.Format.Format_RGB32)
    for _ in range(5):
        sphere.step(1 / 30, 0.5, "SPEAKING", True, False)
    t0 = time.perf_counter()
    for _ in range(30):
        sphere.step(1 / 30, 0.5, "SPEAKING", True, False)
        p = QPainter(img)
        sphere.paint(p, 260, 260, 170, QColor("#00d4ff"), QColor("#00d4ff"), QColor("#000"))
        p.end()
    per_frame = (time.perf_counter() - t0) / 30 * 1000
    assert per_frame < 8.0, f"{per_frame:.1f} ms"


def test_default_style_is_sphere(fake_config):
    from memory.config_manager import get_hud_style, HUD_STYLES
    assert get_hud_style() == "sphere"
    fake_config["hud_style"] = "bogus"
    assert get_hud_style() == "sphere"
    assert HUD_STYLES[0] == "sphere"
