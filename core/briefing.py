"""
Briefing v2 — the facts the morning briefing speaks from, gathered in one
pass alongside the news: today's calendar, unread mail, system health and
anything new on the network overnight.

Personal sections (calendar, mail) are left out while guest mode is on, and
every section is optional: a source that is not set up or fails is simply
skipped, never an error in the briefing.
"""
from __future__ import annotations

import datetime as dt


def _calendar(lines: list[str]) -> None:
    from core import google_services as g
    if g.status() != "ready":
        return
    events = g.upcoming_events(hours=16, limit=5) or []
    if events:
        lines.append("CALENDAR: " + "; ".join(g.describe_event(e) for e in events))
    else:
        lines.append("CALENDAR: nothing scheduled today.")


def _mail(lines: list[str]) -> None:
    from core import google_services as g
    if g.status() != "ready":
        return
    s = g.unread_summary(limit=4) or {"count": 0, "messages": []}
    if s["count"]:
        senders = ", ".join(dict.fromkeys(m["from"] for m in s["messages"]))
        lines.append(f"MAIL: {s['count']} unread (latest from {senders}).")
    else:
        lines.append("MAIL: inbox zero.")


def _system(lines: list[str]) -> None:
    import psutil
    from actions.system_monitor import get_system_status
    s = get_system_status()
    issues = []
    if s["ram_percent"] >= 85:
        issues.append(f"memory at {s['ram_percent']:.0f}%")
    try:
        root = "C:\\" if psutil.WINDOWS else "/"
        disk = psutil.disk_usage(root)
        if disk.percent >= 90:
            issues.append(f"system drive {disk.percent:.0f}% full ({disk.free / 1024 ** 3:.0f} GB free)")
    except Exception:
        pass
    if s.get("cpu_temp_c") and s["cpu_temp_c"] >= 80:
        issues.append(f"CPU at {s['cpu_temp_c']:.0f}°C")
    lines.append("SYSTEM: " + ("attention — " + ", ".join(issues) if issues else "all nominal")
                 + f" (up {s['uptime']}).")


def _network(lines: list[str], now: dt.datetime) -> None:
    from core.security_watch import get_watch
    since = now - dt.timedelta(hours=24)
    new = []
    for mac, info in get_watch()._known.items():
        try:
            seen = dt.datetime.strptime(info.get("first_seen", ""), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if seen >= since:
            new.append(info.get("name") or info.get("ip") or mac)
    if new:
        lines.append(f"NETWORK: {len(new)} device(s) first seen in the last 24 h: {', '.join(new[:4])}.")


def build_digest(now: dt.datetime | None = None) -> list[str]:
    """Lines for the briefing, most important first."""
    from core.access import get_guard
    now = now or dt.datetime.now()
    lines: list[str] = []
    sections = [_system, lambda l: _network(l, now)]
    if not get_guard().guest:
        sections = [_calendar, _mail] + sections
    for fn in sections:
        try:
            fn(lines)
        except Exception as e:
            print(f"[Briefing] section skipped: {e}")
    return lines
