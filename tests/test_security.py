import pytest

LAN = {"aa:00:00:00:00:01": "192.168.1.1", "aa:00:00:00:00:02": "192.168.1.20"}


@pytest.fixture
def sw(tmp_path, monkeypatch, fake_config):
    import core.security_watch as mod
    monkeypatch.setattr(mod, "_KNOWN_PATH", tmp_path / "known.json")
    monkeypatch.setattr(mod, "_removable", lambda: {})
    lan = dict(LAN)
    monkeypatch.setattr(mod, "scan_arp", lambda: dict(lan))
    mod._test_lan = lan
    return mod


def _check_now(w):
    w._last_net = -1e9
    return w.check()


def test_first_scan_is_a_silent_baseline(sw):
    w = sw.SecurityWatch()
    assert _check_now(w) is None
    assert set(w._known) == set(LAN)


def test_new_device_alerts_once_and_survives_restart(sw):
    w = sw.SecurityWatch()
    _check_now(w)
    sw._test_lan["bb:00:00:00:00:09"] = "192.168.1.99"
    alert = _check_now(w)
    assert alert and "192.168.1.99" in alert and alert.startswith("[SYSTEM_ALERT]")
    assert _check_now(w) is None                       # not repeated
    assert _check_now(sw.SecurityWatch()) is None      # persisted across restarts


def test_removable_drive_alert(sw, monkeypatch):
    w = sw.SecurityWatch()
    monkeypatch.setattr(sw, "_removable", lambda: {"E:\\": "FAT32"})
    assert "E:\\" in w._check_drives()
    assert w._check_drives() is None


def test_label_and_report(sw):
    w = sw.SecurityWatch()
    _check_now(w)
    assert "labelled 'Router'" in w.label_device("192.168.1.1", "Router")
    report = w.report()
    assert "Router — 192.168.1.1" in report and "2 known" in report
    assert "No known device" in w.label_device("10.0.0.1", "x")


def test_disabled_in_config(sw, fake_config):
    fake_config["security_watch_enabled"] = False
    assert sw.SecurityWatch().check() is None


def test_multicast_and_broadcast_are_ignored():
    from core.security_watch import _is_unicast
    assert _is_unicast("a0:18:42:9e:a6:99")
    assert not _is_unicast("01:00:5e:00:00:16")
    assert not _is_unicast("ff:ff:ff:ff:ff:ff")


def test_app_itself_is_never_a_suspicious_process():
    import sys
    import core.security_watch as mod
    assert mod._canon(sys.executable).startswith(mod._APP_ROOT) or \
        not mod._canon(sys.executable).startswith(mod._risky_dirs())


def test_real_arp_scan_smoke():
    from core.security_watch import scan_arp
    assert isinstance(scan_arp(), dict)
