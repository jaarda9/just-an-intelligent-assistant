"""
Google Calendar + Gmail — read-only.

Setup (once): create an OAuth client of type "Desktop app" in your own Google
Cloud project, download its JSON as config/client_secret.json, then say
"connect my Google account" (or run connect()). A browser window asks for
consent; the resulting token is stored in config/google_token.json. Both
files are git-ignored and never leave this machine.

Scopes are READ-ONLY: JARVIS can read your schedule and your inbox, never
send, delete or change anything.
"""
from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET = ROOT / "config" / "client_secret.json"
TOKEN_PATH = ROOT / "config" / "google_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]
SETUP_HELP = (
    "Google is not set up yet. One-time setup: in Google Cloud Console create a "
    "project, enable the Google Calendar API and the Gmail API, create an OAuth "
    "client ID of type 'Desktop app', download its JSON and save it as "
    "config/client_secret.json in the JARVIS folder. Then ask me to connect your "
    "Google account."
)

_lock = threading.Lock()
_services: dict[str, object] = {}


def status() -> str:
    """'ready' | 'needs_consent' | 'needs_client'."""
    if TOKEN_PATH.exists():
        return "ready"
    return "needs_consent" if CLIENT_SECRET.exists() else "needs_client"


def _credentials(interactive: bool = False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return creds
    if not interactive:
        return None
    if not CLIENT_SECRET.exists():
        raise FileNotFoundError(SETUP_HELP)
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True,
                                  authorization_prompt_message="",
                                  success_message="JARVIS is connected. You can close this tab.")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect() -> str:
    """Interactive consent in the browser (blocks until done)."""
    with _lock:
        _services.clear()
        try:
            _credentials(interactive=True)
        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Google sign-in failed: {e}"
    return "Connected to Google (read-only: calendar and mail)."


def disconnect() -> str:
    with _lock:
        _services.clear()
        TOKEN_PATH.unlink(missing_ok=True)
    return "Google disconnected; the stored token was deleted."


def _service(name: str, version: str):
    with _lock:
        if name not in _services:
            creds = _credentials(interactive=False)
            if creds is None:
                return None
            from googleapiclient.discovery import build
            _services[name] = build(name, version, credentials=creds, cache_discovery=False)
        return _services[name]


# ── Calendar ────────────────────────────────────────────────────────────────
def _parse(when: dict) -> tuple[dt.datetime, bool]:
    """Event start/end → (aware datetime, all_day)."""
    if "dateTime" in when:
        return dt.datetime.fromisoformat(when["dateTime"].replace("Z", "+00:00")), False
    d = dt.date.fromisoformat(when["date"])
    return dt.datetime.combine(d, dt.time.min).astimezone(), True


def upcoming_events(hours: float = 24, limit: int = 10) -> Optional[list[dict]]:
    """Events starting in the next `hours` (None if not connected)."""
    svc = _service("calendar", "v3")
    if svc is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    items = svc.events().list(
        calendarId="primary", timeMin=now.isoformat(),
        timeMax=(now + dt.timedelta(hours=hours)).isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=limit,
    ).execute().get("items", [])
    out = []
    for e in items:
        start, all_day = _parse(e.get("start", {}))
        end, _ = _parse(e.get("end", e.get("start", {})))
        out.append({"id": e.get("id", ""), "summary": e.get("summary") or "(no title)",
                    "start": start, "end": end, "all_day": all_day,
                    "location": e.get("location") or ""})
    return out


def describe_event(e: dict, now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    if e["all_day"]:
        when = "all day"
    else:
        mins = int((e["start"] - now).total_seconds() // 60)
        local = e["start"].astimezone().strftime("%H:%M")
        when = (f"in {mins} min ({local})" if 0 <= mins < 90 else
                "now" if mins < 0 else f"at {local}")
    loc = f" — {e['location']}" if e["location"] else ""
    return f"{e['summary']} {when}{loc}"


# ── Gmail ───────────────────────────────────────────────────────────────────
def unread_summary(limit: int = 8) -> Optional[dict]:
    """{'count': N, 'messages': [{'from','subject'}…]} (None if not connected)."""
    svc = _service("gmail", "v1")
    if svc is None:
        return None
    res = svc.users().messages().list(userId="me", q="is:unread in:inbox",
                                      maxResults=limit).execute()
    msgs = []
    for m in res.get("messages", []):
        meta = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["From", "Subject"]).execute()
        hdr = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
        sender = hdr.get("From", "")
        sender = sender.split("<")[0].strip().strip('"') or sender
        msgs.append({"from": sender, "subject": hdr.get("Subject", "(no subject)")})
    return {"count": int(res.get("resultSizeEstimate", len(msgs))), "messages": msgs}


# ── reminders ───────────────────────────────────────────────────────────────
class MeetingReminder:
    """Checks the calendar every minute; returns a note once per event when
    it is about to start (lead minutes before)."""

    def __init__(self, lead_min: int = 10):
        self.lead = lead_min
        self._told: set[str] = set()
        self._last_poll = 0.0
        self._cache: list[dict] = []

    def check(self, now: Optional[dt.datetime] = None, poll_every: float = 300.0) -> Optional[str]:
        import time
        if status() != "ready":
            return None
        if time.monotonic() - self._last_poll > poll_every:
            self._last_poll = time.monotonic()
            try:
                self._cache = upcoming_events(hours=2, limit=10) or []
            except Exception as e:
                print(f"[Google] calendar poll failed: {e}")
                return None
        now = now or dt.datetime.now(dt.timezone.utc)
        for e in self._cache:
            if e["all_day"] or e["id"] in self._told:
                continue
            mins = (e["start"] - now).total_seconds() / 60
            if 0 <= mins <= self.lead:
                self._told.add(e["id"])
                return (f"[CALENDAR] Upcoming: {describe_event(e, now)}. Remind the user in "
                        f"one short sentence in their language. Call no tools.")
        return None
