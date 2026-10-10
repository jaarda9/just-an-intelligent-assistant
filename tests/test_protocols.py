import json

import pytest

from conftest import FakePlayer


@pytest.fixture
def protocols(tmp_path, monkeypatch):
    from plugins import protocols as mod
    monkeypatch.setattr(mod, "PROTOCOLS_PATH", tmp_path / "protocols.json")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def test_starter_file_is_created_and_listed(protocols, player):
    out = protocols.run({"action": "list"}, player=player)
    assert protocols.PROTOCOLS_PATH.exists()
    assert "work" in out and "night" in out and "status" in out


def test_alias_and_fuzzy_match_run_steps_in_order(protocols, player):
    out = protocols.run({"name": "good night protocol"}, player=player)
    assert [c[0] for c in player.calls] == ["computer_settings"] * 3
    assert [c[1]["action"] for c in player.calls] == ["mute", "brightness_down", "lock_screen"]
    assert "3/3 steps succeeded" in out


def test_unknown_protocol_names_what_exists(protocols, player):
    out = protocols.run({"name": "house party"}, player=player)
    assert "no protocol called" in out.lower() and "work" in out
    assert not player.calls


def test_failures_are_reported_not_hidden(protocols):
    p = FakePlayer(tools={"open_app": lambda a: f"Failed to open {a['app_name']}"})
    out = protocols.run({"name": "work"}, player=p)
    # work = volume + open VS Code + open Spotify; both opens fail
    assert "1/3 steps succeeded" in out
    assert "Visual Studio Code" in out and "Spotify" in out


def test_protocol_cannot_start_a_protocol(protocols, player):
    protocols.PROTOCOLS_PATH.write_text(json.dumps({
        "loop": {"steps": [{"tool": "run_protocol", "args": {"name": "loop"}}]}}))
    out = protocols.run({"name": "loop"}, player=player)
    assert not player.calls
    assert "cannot be used in a protocol" in out


def test_invalid_json_is_explained(protocols, player):
    protocols.PROTOCOLS_PATH.write_text("{ not json")
    assert "not valid JSON" in protocols.run({"name": "work"}, player=player)


def test_needs_the_dispatcher(protocols):
    assert "dispatcher" in protocols.run({"name": "work"}, player=None)
