import datetime as dt

import pytest


@pytest.fixture
def b(monkeypatch, tmp_path):
    import core.briefing as br
    import core.google_services as g
    import core.access as access
    import core.security_watch as sw
    guard = access.AccessGuard()
    monkeypatch.setattr(access, "_guard", guard)
    monkeypatch.setattr(g, "status", lambda: "ready")
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
    monkeypatch.setattr(g, "upcoming_events", lambda **k: [
        {"id": "1", "summary": "Board meeting", "start": start, "end": start,
         "all_day": False, "location": ""}])
    monkeypatch.setattr(g, "unread_summary", lambda **k: {
        "count": 3, "messages": [{"from": "Pepper", "subject": "a"}, {"from": "Pepper", "subject": "b"},
                                 {"from": "Happy", "subject": "c"}]})
    w = sw.SecurityWatch.__new__(sw.SecurityWatch)
    now = dt.datetime(2026, 10, 12, 8, 0)
    w._known = {"aa": {"ip": "192.168.1.50", "first_seen": "2026-10-12 02:13", "name": ""},
                "bb": {"ip": "192.168.1.1", "first_seen": "2026-09-01 10:00", "name": "Router"}}
    monkeypatch.setattr(sw, "get_watch", lambda: w)
    return br, guard, now


def test_digest_has_every_section_in_order(b):
    br, guard, now = b
    lines = br.build_digest(now)
    assert [l.split(":")[0] for l in lines] == ["CALENDAR", "MAIL", "SYSTEM", "NETWORK"]
    assert "Board meeting in" in lines[0]
    assert lines[1] == "MAIL: 3 unread (latest from Pepper, Happy)."
    assert "192.168.1.50" in lines[3] and "Router" not in lines[3]


def test_guest_mode_drops_personal_sections(b):
    br, guard, now = b
    guard.enter_guest("t")
    heads = [l.split(":")[0] for l in br.build_digest(now)]
    assert "CALENDAR" not in heads and "MAIL" not in heads and "SYSTEM" in heads


def test_failing_source_is_skipped_not_fatal(b, monkeypatch):
    br, guard, now = b
    import core.google_services as g

    def boom(**k):
        raise RuntimeError("network down")
    monkeypatch.setattr(g, "upcoming_events", boom)
    heads = [l.split(":")[0] for l in br.build_digest(now)]
    assert "CALENDAR" not in heads and "MAIL" in heads
