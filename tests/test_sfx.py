import numpy as np
import pytest


def test_every_sound_is_finite_and_short():
    from core import sfx
    for name, sig in sfx._designs().items():
        assert np.isfinite(sig).all(), name
        assert 0.02 < len(sig) / sfx._SR < 2.5, name


@pytest.mark.parametrize("prev,new,expected", [
    ("LISTENING", "THINKING", "tick"),
    ("THINKING", "LISTENING", "done"),
    ("SLEEPING", "LISTENING", "wake"),
    ("LISTENING", "SLEEPING", "sleep"),
    ("SPEAKING", "LISTENING", None),       # every-turn flip stays silent
    ("INITIALISING", "LISTENING", None),   # the boot tone covers this
    ("LISTENING", "LISTENING", None),
])
def test_state_edges(monkeypatch, prev, new, expected):
    from core import sfx
    played = []
    monkeypatch.setattr(sfx, "play", played.append)
    sfx.on_state_change(prev, new)
    assert played == ([expected] if expected else [])
