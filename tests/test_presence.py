"""Presence state machine with a simulated camera — the real webcam is never
opened and no model files are needed."""
import numpy as np
import pytest


def _unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import core.presence as pr
    rng = np.random.default_rng(0)
    owner = _unit(rng.normal(size=128))
    stranger = _unit(rng.normal(size=128))
    near_owner = _unit(owner + 0.05 * rng.normal(size=128))
    np.save(tmp_path / "owner.npy", owner)

    cfg = {"presence_enabled": True}
    monkeypatch.setattr(pr, "_OWNER_PATH", tmp_path / "owner.npy")
    monkeypatch.setattr(pr, "_config", lambda: cfg)
    monkeypatch.setattr(pr, "_set_config", lambda k, v: cfg.__setitem__(k, v))
    monkeypatch.setattr(pr, "models_ready", lambda: True)

    p = pr.Presence()
    p._owner = owner
    scene = {"faces": []}
    p._load = lambda: None
    p._grab = lambda frames=1, **k: [np.zeros((10, 10, 3), np.uint8)]
    p._faces = lambda frame: [(e, 120.0) for e in scene["faces"]]

    def look(*faces):
        scene["faces"] = list(faces)
        p._last_look = 0
        return p.check()

    return p, look, cfg, owner, near_owner, stranger


def test_full_scenario(rig):
    p, look, cfg, owner, near, stranger = rig
    assert look(near) is None and p._here is True
    look(); look()
    assert p._here is False
    p._away_since -= 600
    alert = look(stranger)
    assert alert and alert.startswith("[SYSTEM_ALERT]")
    assert look(stranger) is None                          # cooldown
    welcome = look(near)
    assert welcome and welcome.startswith("[PRESENCE]") and "10 minutes" in welcome


def test_short_absence_gets_no_greeting(rig):
    p, look, *_ = rig
    near = rig[4]
    look(near); look(); look()
    assert look(near) is None


def test_stranger_with_owner_present_is_not_an_alert(rig):
    p, look, cfg, owner, near, stranger = rig
    assert look(near, stranger) is None


def test_off_means_off(rig):
    p, look, cfg, *_ = rig
    cfg["presence_enabled"] = False
    assert look(rig[4]) is None


def test_enable_requires_enrolment(rig, tmp_path):
    p, look, cfg, *_ = rig
    (tmp_path / "owner.npy").unlink()
    assert "enrolled first" in p.set_enabled(True)


def test_forget_deletes_face_and_disables(rig, tmp_path):
    p, look, cfg, *_ = rig
    p.forget()
    assert not (tmp_path / "owner.npy").exists()
    assert cfg["presence_enabled"] is False


def test_model_hashes_are_pinned():
    import core.presence as pr
    for name, url, sha in pr._MODELS.values():
        assert url.startswith("https://github.com/opencv/opencv_zoo/")
        assert len(sha) == 64
