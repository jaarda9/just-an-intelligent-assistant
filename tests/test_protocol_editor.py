import json

import pytest


def test_validate_rules():
    from core.protocol_store import validate
    ok = {"steps": [{"tool": "open_app", "args": {"app_name": "x"}}]}
    assert validate("work", ok) == []
    assert validate("Bad Name!", ok)
    assert validate("x", {"steps": []})
    assert validate("x", {"steps": [{"tool": "run_protocol"}]})
    assert validate("x", {"steps": [{"wait": 99}]})
    assert validate("x", {**ok, "triggers": [{"at": "25:00"}]})
    assert validate("x", {**ok, "triggers": [{"on": "lunchtime"}]})
    assert validate("x", {**ok, "triggers": [{"at": "07:00", "days": ["mon"]}, {"on": "arrive"}]}) == []


def test_save_rename_delete(protocols_file):
    from core import protocol_store as store
    store.load_all()                                       # creates the starter file
    proto = {"aliases": ["Movie Time ", ""], "announce": " Lights down. ",
             "steps": [{"tool": "computer_settings", "args": {"action": "mute"}}],
             "triggers": [{"on": "arrive"}]}
    assert store.save("cinema", proto) == []
    data = json.loads(protocols_file.read_text())
    assert data["cinema"]["aliases"] == ["movie time"] and data["cinema"]["announce"] == "Lights down."
    assert "_readme" in data                               # file notes preserved
    assert store.save("work", proto) != []                 # name clash refused
    assert store.save("movies", proto, old_name="cinema") == []
    data = json.loads(protocols_file.read_text())
    assert "movies" in data and "cinema" not in data
    assert store.delete("movies") and not store.delete("movies")


def test_editor_builds_and_saves_a_protocol(qapp, protocols_file):
    from ui.protocol_editor import ProtocolEditor
    ed = ProtocolEditor(None)
    assert ed._list.count() == 3                           # starter protocols
    ed._new()
    ed._name.setText("focus")
    ed._tool.setCurrentIndex(ed._tool.findData("open_app"))
    ed._param_edits["app_name"].setText("Notepad")
    ed._add_step()
    ed._add_wait()
    ed._time.setTime(ed._time.time().fromString("08:30", "HH:mm"))
    ed._add_time_trigger()
    ed._event.setCurrentIndex(ed._event.findData("leave"))
    ed._add_event_trigger()
    assert ed._save()
    saved = json.loads(protocols_file.read_text())["focus"]
    assert saved["steps"][0] == {"tool": "open_app", "args": {"app_name": "Notepad"}}
    assert saved["steps"][1] == {"wait": 1.0}
    assert saved["triggers"][0] == {"at": "08:30", "days": ["mon", "tue", "wed", "thu", "fri"]}
    assert saved["triggers"][1] == {"on": "leave"}
    # reorder + remove
    ed._step_list.setCurrentRow(1); ed._move(-1)
    assert "wait" in ed._steps[0]
    ed._remove_step()
    assert len(ed._steps) == 1


def test_editor_reports_validation_errors(qapp, protocols_file):
    from ui.protocol_editor import ProtocolEditor
    ed = ProtocolEditor(None)
    ed._new()
    ed._name.setText("empty")
    assert not ed._save()
    assert "at least one step" in ed._status.text()


def test_run_protocol_is_never_offered_as_a_step(qapp, protocols_file):
    from ui.protocol_editor import ProtocolEditor
    cat = [{"name": "run_protocol", "params": {}}, {"name": "open_app", "params": {"app_name": ""}}]
    ed = ProtocolEditor(cat)
    assert ed._tool.findData("run_protocol") == -1 and ed._tool.findData("open_app") >= 0
