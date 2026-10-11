"""Multi-monitor screen selection (no real capture)."""
import pytest

# The owner's real layout: primary on top at (0,0); a second screen below it,
# shifted left — and mss lists that secondary one FIRST.
STACKED = [
    {"left": -529, "top": 0, "width": 2449, "height": 2160},
    {"left": -529, "top": 1080, "width": 1920, "height": 1080, "is_primary": False},
    {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True},
]
SIDE = [
    {"left": 0, "top": 0, "width": 3840, "height": 1080},
    {"left": 0, "top": 0, "width": 1920, "height": 1080},
    {"left": 1920, "top": 0, "width": 1920, "height": 1080},
]


@pytest.mark.parametrize("which,expect_top,expect_left", [
    ("primary", 0, 0), ("secondary", 1080, -529), ("2", 1080, -529),
    ("top", 0, 0), ("bottom", 1080, -529), ("lower", 1080, -529),
])
def test_stacked_layout(which, expect_top, expect_left):
    from actions.screen_processor import _pick_monitor
    m, label = _pick_monitor(STACKED, which, cursor=(10, 10))
    assert (m["top"], m["left"]) == (expect_top, expect_left), label


def test_old_bug_primary_is_not_monitors_1():
    """The old code always captured monitors[1] — here the secondary screen."""
    from actions.screen_processor import _pick_monitor
    m, label = _pick_monitor(STACKED, "primary", cursor=(10, 10))
    assert m is STACKED[2] and m is not STACKED[1]


def test_auto_follows_the_mouse():
    from actions.screen_processor import _pick_monitor
    m, label = _pick_monitor(STACKED, "auto", cursor=(422, 1234))
    assert m is STACKED[1] and "with the mouse" in label
    m, label = _pick_monitor(SIDE, "auto", cursor=(2500, 500))
    assert m is SIDE[2]
    m, label = _pick_monitor(SIDE, "auto", cursor=None)       # cursor unknown → primary
    assert m is SIDE[1] or "primary" in label


def test_all_and_left_right():
    from actions.screen_processor import _pick_monitor
    assert _pick_monitor(SIDE, "all")[0] is SIDE[0]
    assert _pick_monitor(SIDE, "both")[0] is SIDE[0]
    assert _pick_monitor(SIDE, "left")[0] is SIDE[1]
    assert _pick_monitor(SIDE, "right")[0] is SIDE[2]


def test_single_screen():
    from actions.screen_processor import _pick_monitor
    one = [{"left": 0, "top": 0, "width": 1920, "height": 1080}] * 2
    assert _pick_monitor(one, "secondary")[1] == "the only screen"
