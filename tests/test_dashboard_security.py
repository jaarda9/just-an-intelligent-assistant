"""Phone dashboard hardening (Mark IV 4.3)."""
import inspect
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def dash(tmp_path, monkeypatch):
    import dashboard.server as ds
    monkeypatch.setattr(ds, "UPLOADS_DIR", tmp_path)
    srv = ds.DashboardServer()
    srv._uploads_dir = tmp_path
    return ds, srv, TestClient(srv.app)


def test_pairing_code_brute_force_is_rate_limited(dash):
    ds, srv, c = dash
    key = srv.new_key()
    for i in range(ds._FAIL_PER_IP):
        assert c.post("/login", json={"pin": f"WRONG{i}"}).status_code == 401
    # even the right code is refused once the address is locked out
    assert c.post("/login", json={"pin": key}).status_code == 429
    assert c.get(f"/auto-login?key={key}").status_code == 429


def test_valid_login_then_token_expiry(dash):
    ds, srv, c = dash
    key = srv.new_key()
    tok = c.post("/login", json={"pin": key}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert c.post("/api/wake", headers=hdr).status_code == 200
    srv._tokens[tok] = time.time() - 1                    # expire it
    assert c.post("/api/wake", headers=hdr).status_code == 401
    assert tok not in srv._tokens                         # and it is purged
    # one-time code cannot be reused
    assert c.post("/login", json={"pin": key}).status_code == 401


def test_expired_device_token_rejected(dash):
    ds, srv, c = dash
    srv._device_sessions["dev"] = {"session_key": "K", "expires": time.time() - 1}
    assert c.post("/api/device-login", json={"device_token": "dev"}).status_code == 401
    srv._device_sessions["dev2"] = {"session_key": "K", "expires": time.time() + 60}
    assert c.post("/api/device-login", json={"device_token": "dev2"}).json()["ok"]


def test_download_is_confined_to_uploads(dash, tmp_path):
    ds, srv, c = dash
    tok = srv._issue_token("K")
    (tmp_path / "ok.txt").write_text("hello")
    (tmp_path.parent / "secret.txt").write_text("SECRET-7f3a9c")
    assert c.get(f"/uploads/ok.txt?token={tok}").text == "hello"
    for bad in ("..%2Fsecret.txt", "..%5Csecret.txt", "ok.txt%3Astream"):
        assert c.get(f"/uploads/{bad}?token={tok}").status_code == 404, bad
    # a bare ".." is normalised to "/" by the HTTP client (the index page);
    # whatever route answers, the file outside uploads must never come back
    assert "SECRET-7f3a9c" not in c.get(f"/uploads/..?token={tok}").text
    assert c.get("/uploads/ok.txt?token=wrong").status_code == 401


def test_fonts_route_serves_only_bundled_ttf(dash):
    ds, srv, c = dash
    assert c.get("/static/fonts/Rajdhani-Bold.ttf").status_code == 200
    assert c.get("/static/fonts/..%2F..%2Fconfig%2Fapi_keys.json").status_code == 404


def test_crypto_js_integrity_check(tmp_path, monkeypatch):
    import dashboard.server as ds
    monkeypatch.setattr(ds, "_CRYPTOJS_FILE", tmp_path / "c.js")
    (tmp_path / "c.js").write_text("alert('tampered')")
    assert not ds._crypto_js_ok()


def test_firewall_change_is_narrow():
    """No network re-categorisation, no program-wide allow rule; LAN only."""
    import dashboard.server as ds
    src = inspect.getsource(ds._ensure_network_access)
    win = src.split("# ── macOS")[0]
    assert "Set-NetConnectionProfile" not in win
    assert "program=" not in win
    assert "remoteip=localsubnet" in win


def test_nothing_listens_until_asked(dash):
    ds, srv, c = dash
    assert srv.started is False
