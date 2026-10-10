"""
Google Calendar + Gmail, read-only — front-end to core/google_services.py.
"""
import threading

from core import google_services as g

PLUGIN = {
    "name": "google_services",
    "description": (
        "The owner's Google Calendar and Gmail, READ-ONLY. action='agenda' for "
        "today's / upcoming events ('what's on my calendar', 'do I have meetings'), "
        "'next_meeting', 'unread_mail' ('any new emails', 'who emailed me'), "
        "'connect' to sign in to Google (opens a browser), 'disconnect', 'status'. "
        "It cannot send mail or create events."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "agenda | next_meeting | unread_mail | connect | disconnect | status"},
            "hours": {"type": "NUMBER", "description": "For agenda: how far ahead (default 24)."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action") or "status").lower().strip()

    if action == "connect":
        if g.status() == "needs_client":
            return g.SETUP_HELP
        # The browser consent can take a minute — don't hold the tool call.
        def go():
            msg = g.connect()
            if player:
                try:
                    player.write_log(f"SYS: {msg}")
                    player.notify("Google", msg, "ok" if msg.startswith("Connected") else "alert")
                except Exception:
                    pass
        threading.Thread(target=go, daemon=True, name="google-connect").start()
        return ("A Google sign-in page is opening in the browser. Tell the user to "
                "approve read-only access there; you will be connected once they do.")
    if action == "disconnect":
        return g.disconnect()
    st = g.status()
    if action == "status":
        return {"ready": "Google is connected (read-only calendar and mail).",
                "needs_consent": "Google client is installed but not signed in yet — ask me to connect.",
                "needs_client": g.SETUP_HELP}[st]
    if st != "ready":
        return g.SETUP_HELP if st == "needs_client" else \
            "Google is not connected yet — ask me to connect your Google account."

    try:
        if action in ("agenda", "next_meeting"):
            hours = float(parameters.get("hours") or (24 if action == "agenda" else 72))
            events = g.upcoming_events(hours=hours, limit=10 if action == "agenda" else 1) or []
            if not events:
                return f"Nothing on the calendar in the next {int(hours)} hours."
            if action == "next_meeting":
                return "Next: " + g.describe_event(events[0]) + "."
            lines = [g.describe_event(e) for e in events]
            if player:
                try:
                    player.show_content("AGENDA", "\n".join(lines))
                except Exception:
                    pass
            return f"{len(events)} event(s): " + "; ".join(lines) + "."
        if action == "unread_mail":
            s = g.unread_summary() or {"count": 0, "messages": []}
            if not s["count"]:
                return "Inbox zero — no unread mail."
            lines = [f"{m['from']}: {m['subject']}" for m in s["messages"]]
            if player:
                try:
                    player.show_content("UNREAD MAIL", "\n".join(lines))
                except Exception:
                    pass
            return f"{s['count']} unread. Latest: " + "; ".join(lines[:5]) + "."
    except Exception as e:
        return f"Google request failed: {e}"
    return f"Unknown action '{action}'."
