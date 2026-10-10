import datetime as dt
import json

import numpy as np
import pytest


@pytest.fixture
def engine(tmp_path, monkeypatch):
    import importlib
    import sys
    import core.triggers as tr
    import plugins
    monkeypatch.setattr(tr, "STATE_PATH", tmp_path / "state.json")
    # The plugin loader (test_loaders) re-executes plugins/protocols.py into
    # sys.modules, so the package attribute and sys.modules can hold two
    # different module objects. Patch every copy the engine might import.
    importlib.import_module("plugins.protocols")
    for mod in {id(m): m for m in (sys.modules["plugins.protocols"],
                                   getattr(plugins, "protocols", None)) if m}.values():
        monkeypatch.setattr(mod, "PROTOCOLS_PATH", tmp_path / "p.json")
    (tmp_path / "p.json").write_text(json.dumps({
        "work":  {"steps": [], "triggers": [{"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
                                            {"on": "arrive"}]},
        "night": {"steps": [], "triggers": [{"at": "23:30"}, {"on": "leave"}]},
        "boot":  {"steps": [], "triggers": [{"on": "startup"}]},
        "plain": {"steps": []},
    }))
    clock = {"now": dt.datetime(2026, 10, 12, 9, 0)}          # a Monday
    ran = []
    e = tr.TriggerEngine(lambda n, why: ran.append((n, why)), now=lambda: clock["now"])
    return tr, e, clock, ran, tmp_path


def test_time_trigger_fires_once_per_day(engine):
    tr, e, clock, ran, _ = engine
    assert e.tick() == ["work"]
    clock["now"] = dt.datetime(2026, 10, 12, 9, 4)
    assert e.tick() == []                                    # same day: not again
    clock["now"] = dt.datetime(2026, 10, 13, 9, 1)           # Tuesday
    assert e.tick() == ["work"]
    assert ran[0] == ("work", "scheduled at 09:00 weekdays")


def test_weekday_filter_and_late_start(engine):
    tr, e, clock, ran, _ = engine
    clock["now"] = dt.datetime(2026, 10, 17, 9, 0)           # Saturday
    assert e.tick() == []
    clock["now"] = dt.datetime(2026, 10, 19, 12, 0)          # Monday noon: missed window
    assert e.tick() == []


def test_restart_does_not_double_fire(engine):
    tr, e, clock, ran, tmp = engine
    e.tick()
    e2 = tr.TriggerEngine(lambda n, w: ran.append(n), now=lambda: clock["now"])
    assert e2.tick() == []                                   # state persisted


def test_events(engine):
    tr, e, clock, ran, _ = engine
    assert e.fire_event("arrive") == ["work"]
    assert e.fire_event("leave") == ["night"]
    assert e.fire_event("startup") == ["boot"]
    assert e.fire_event("nonsense") == []


def test_describe():
    from core.triggers import describe
    assert describe({"at": "07:15"}) == "at 07:15 every day"
    assert describe({"at": "07:15", "days": ["sat", "sun"]}) == "at 07:15 weekends"
    assert describe({"on": "arrive"}) == "when you sit down"


def test_presence_emits_arrive_and_leave(tmp_path, monkeypatch):
    import core.presence as pr
    import core.access as access
    monkeypatch.setattr(access, "_guard", access.AccessGuard())
    rng = np.random.default_rng(2)
    owner = rng.normal(size=128).astype(np.float32); owner /= np.linalg.norm(owner)
    np.save(tmp_path / "o.npy", owner)
    monkeypatch.setattr(pr, "_OWNER_PATH", tmp_path / "o.npy")
    monkeypatch.setattr(pr, "_config", lambda: {"presence_enabled": True})
    monkeypatch.setattr(pr, "models_ready", lambda: True)
    p = pr.Presence(); p._owner = owner; p._load = lambda: None
    scene = {"f": []}
    p._grab = lambda frames=1, **k: [np.zeros((4, 4, 3), np.uint8)]
    p._faces = lambda fr: [(x, 120.0) for x in scene["f"]]
    events = []
    p.on_event(events.append)

    def look(*faces):
        scene["f"] = list(faces); p._last_look = 0; p.check()

    look(owner); look(); look(); look(owner)
    assert events == ["leave", "arrive"]
