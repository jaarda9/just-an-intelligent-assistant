"""Every bundled action and plugin must load — a broken import is caught here,
not at launch in front of the user."""
from conftest import ROOT


def test_all_plugins_load():
    from core.plugin_loader import discover_plugins
    reg = discover_plugins(ROOT / "plugins", core_tool_names=set(), logger=lambda m: None)
    bad = [(r.file, r.error) for r in reg._all_records if not r.valid]
    assert not bad, bad
    for name in ("run_protocol", "run_diagnostics", "security_report", "presence"):
        assert reg.has(name), name


def test_all_actions_load():
    from core.action_loader import discover_actions
    reg = discover_actions(ROOT / "actions", logger=lambda m: None)
    bad = [(r.file, r.error) for r in reg._all_records if not r.valid]
    assert not bad, bad
    assert {"open_app", "computer_settings", "web_search"} <= reg.names()


def test_plugin_and_action_names_do_not_collide():
    from core.action_loader import discover_actions
    from core.plugin_loader import discover_plugins
    actions = discover_actions(ROOT / "actions", logger=lambda m: None)
    reg = discover_plugins(ROOT / "plugins", core_tool_names=actions.names(),
                           logger=lambda m: None)
    collided = [r.file for r in reg._all_records if "collides" in r.error]
    assert not collided, collided
