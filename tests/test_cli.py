"""The `jarvis` terminal command and its loopback channel."""
import json
import socket

import pytest


@pytest.fixture
def server(tmp_path, monkeypatch):
    import core.cli_server as cs
    import jarvis_cli
    monkeypatch.setattr(cs, "INFO_PATH", tmp_path / "cli.json")
    monkeypatch.setattr(jarvis_cli, "INFO", tmp_path / "cli.json")
    seen = []

    def handler(req):
        seen.append(req)
        return {"ok": True, "result": f"{req.get('cmd')}:{req.get('text', '')}"}

    srv = cs.CLIServer(handler)
    srv.start()
    yield srv, seen, tmp_path / "cli.json"
    srv.stop()


def test_round_trip_through_cli(server, capsys):
    import jarvis_cli
    srv, seen, info = server
    assert jarvis_cli.main(["what", "time", "is", "it"]) == 0
    assert capsys.readouterr().out.strip() == "say:what time is it"
    assert jarvis_cli.main(["--protocol", "work"]) == 0
    assert seen[-1]["cmd"] == "protocol" and seen[-1]["text"] == "work"


def test_loopback_only_and_token_required(server):
    srv, seen, info = server
    data = json.loads(info.read_text())
    assert len(data["token"]) == 64
    with socket.create_connection(("127.0.0.1", srv.port), timeout=3) as s:
        s.sendall(b'{"token": "wrong", "cmd": "status"}\n')
        resp = json.loads(s.recv(4096))
    assert resp == {"ok": False, "result": "bad token"}
    assert not seen                                   # handler never ran
    assert srv._sock.getsockname()[0] == "127.0.0.1"


def test_oversized_request_rejected(server):
    srv, seen, info = server
    with socket.create_connection(("127.0.0.1", srv.port), timeout=3) as s:
        s.sendall(b"x" * 20000)
        resp = json.loads(s.recv(4096))
    assert not resp["ok"] and not seen


def test_info_file_removed_on_stop(server):
    srv, seen, info = server
    assert info.exists()
    srv.stop()
    assert not info.exists()


def test_main_handler_commands(monkeypatch):
    import types as _t
    import main
    import core.access as access
    g = access.AccessGuard()
    monkeypatch.setattr(main, "get_guard", lambda: g)
    sent, logs = [], []
    ui = _t.SimpleNamespace(
        _win=_t.SimpleNamespace(hud=_t.SimpleNamespace(state="LISTENING"),
                                _summon_sig=_t.SimpleNamespace(emit=lambda: sent.append("summon"))),
        muted=False, write_log=logs.append)
    fake = _t.SimpleNamespace(ui=ui, session=None,
                              _on_text_command=sent.append,
                              _run_tool_sync=lambda n, a: "[PROTOCOL work] 3/3 steps succeeded. Tell the user …")
    h = lambda req: main.JarvisLive._on_cli(fake, req)
    assert "access: owner" in h({"cmd": "status"})["result"]
    assert h({"cmd": "protocol", "text": "work"}) == {"ok": True, "result": "[PROTOCOL work] 3/3 steps succeeded."}
    assert not h({"cmd": "say", "text": "hi"})["ok"]          # no session yet
    fake.session = object()
    assert h({"cmd": "say", "text": "hi"})["ok"] and sent[-1] == "hi"
    h({"cmd": "summon"}); assert sent[-1] == "summon"
    assert not h({"cmd": "rm -rf"})["ok"]


def test_cli_reports_app_not_running(tmp_path, monkeypatch, capsys):
    import jarvis_cli
    monkeypatch.setattr(jarvis_cli, "INFO", tmp_path / "missing.json")
    assert jarvis_cli.main(["hello"]) == 1
    assert "not running" in capsys.readouterr().out
