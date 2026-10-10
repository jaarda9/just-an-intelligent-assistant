"""Google Calendar + Gmail with the Google API fully mocked — no network,
no credentials, nothing read from a real account."""
import datetime as dt

import pytest

NOW = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.timezone.utc)


class _Exec:
    def __init__(self, data): self._d = data
    def execute(self): return self._d


class FakeCalendar:
    def __init__(self, items): self._items = items
    def events(self): return self
    def list(self, **kw):
        self.kw = kw
        return _Exec({"items": self._items})


class FakeGmail:
    def __init__(self, msgs): self._msgs = msgs
    def users(self): return self
    def messages(self): return self
    def list(self, **kw): return _Exec({"messages": [{"id": m[0]} for m in self._msgs],
                                        "resultSizeEstimate": len(self._msgs)})
    def get(self, userId, id, **kw):
        frm, subj = next((m[1], m[2]) for m in self._msgs if m[0] == id)
        return _Exec({"payload": {"headers": [{"name": "From", "value": frm},
                                              {"name": "Subject", "value": subj}]}})


@pytest.fixture
def g(tmp_path, monkeypatch):
    import core.google_services as gs
    monkeypatch.setattr(gs, "CLIENT_SECRET", tmp_path / "client_secret.json")
    monkeypatch.setattr(gs, "TOKEN_PATH", tmp_path / "google_token.json")
    gs._services.clear()
    yield gs
    gs._services.clear()


def _connect(g, tmp_path, cal_items=(), mails=()):
    g.TOKEN_PATH.write_text("{}")
    g._services["calendar"] = FakeCalendar(list(cal_items))
    g._services["gmail"] = FakeGmail(list(mails))


def test_status_and_setup_help(g):
    assert g.status() == "needs_client"
    g.CLIENT_SECRET.write_text("{}")
    assert g.status() == "needs_consent"
    g.TOKEN_PATH.write_text("{}")
    assert g.status() == "ready"
    assert "config/client_secret.json" in g.SETUP_HELP


def test_upcoming_events_parsed(g, tmp_path):
    _connect(g, tmp_path, cal_items=[
        {"id": "a", "summary": "Stand-up", "start": {"dateTime": "2026-10-12T09:10:00Z"},
         "end": {"dateTime": "2026-10-12T09:25:00Z"}, "location": "Lab"},
        {"id": "b", "summary": "Holiday", "start": {"date": "2026-10-12"}, "end": {"date": "2026-10-13"}},
    ])
    ev = g.upcoming_events()
    assert ev[0]["summary"] == "Stand-up" and not ev[0]["all_day"]
    assert ev[1]["all_day"]
    assert g.describe_event(ev[0], NOW).startswith("Stand-up in 10 min")
    assert g.describe_event(ev[0], NOW).endswith("— Lab")
    assert "singleEvents" in g._services["calendar"].kw     # recurring events expanded


def test_unread_summary(g, tmp_path):
    _connect(g, tmp_path, mails=[("1", '"Pepper Potts" <pepper@stark.com>', "Board meeting"),
                                 ("2", "happy@stark.com", "Car")])
    s = g.unread_summary()
    assert s["count"] == 2
    assert s["messages"][0] == {"from": "Pepper Potts", "subject": "Board meeting"}


def test_meeting_reminder_fires_once(g, tmp_path):
    _connect(g, tmp_path)
    r = g.MeetingReminder(lead_min=10)
    r._last_poll = 10 ** 12                                  # skip polling; use the cache
    start = NOW + dt.timedelta(minutes=8)
    r._cache = [{"id": "x", "summary": "Briefing", "start": start, "end": start,
                 "all_day": False, "location": ""}]
    msg = r.check(now=NOW)
    assert msg and msg.startswith("[CALENDAR] Upcoming: Briefing in 8 min")
    assert r.check(now=NOW) is None
    r2 = g.MeetingReminder(lead_min=10)
    r2._last_poll = 10 ** 12
    r2._cache = [{"id": "y", "summary": "Later", "start": NOW + dt.timedelta(minutes=40),
                  "end": NOW, "all_day": False, "location": ""}]
    assert r2.check(now=NOW) is None


def test_plugin_paths(g, tmp_path):
    from plugins import google_services as plug
    monkey_g = plug.g
    assert "client_secret.json" in plug.run({"action": "agenda"})          # not set up
    _connect(g, tmp_path, cal_items=[{"id": "a", "summary": "Lunch",
                                      "start": {"dateTime": "2099-01-01T12:00:00Z"},
                                      "end": {"dateTime": "2099-01-01T13:00:00Z"}}],
             mails=[("1", "Rhodey <r@usaf.mil>", "Suit")])
    assert "Lunch" in plug.run({"action": "agenda", "hours": 10 ** 6})
    assert plug.run({"action": "unread_mail"}).startswith("1 unread. Latest: Rhodey: Suit")
    assert monkey_g is g


def test_google_is_blocked_in_guest_mode():
    from core.access import AccessGuard
    a = AccessGuard()
    a.enter_guest("t")
    assert a.check("google_services", {"action": "unread_mail"})


def test_agenda_panel_states(qapp):
    from ui.agenda import AgendaPanel
    p = AgendaPanel(); p.resize(180, 160)
    p.show_events(None)
    assert p.isHidden()
    p.show_events("guest")
    assert not p.isHidden() and "guest" in p._note.text()
    start = dt.datetime.now().astimezone() + dt.timedelta(hours=1)
    p.show_events([{"summary": "Suit test", "start": start, "all_day": False}])
    assert p._rows[0][1].text() == "Suit test" and p._note.isHidden()
