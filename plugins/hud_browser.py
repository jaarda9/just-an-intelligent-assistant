"""
HUD browser — open web pages in tabs inside JARVIS's own interface.
Front-end to ui/browser.py via JarvisUI.browser().
"""
from ui.browser import HAVE_WEBENGINE

PLUGIN = {
    "name": "hud_browser",
    "description": (
        "JARVIS's built-in browser: web pages open IN TABS INSIDE THE HUD (like videos do), "
        "not in a separate browser window. This is the DEFAULT way to open or show any "
        "website, page, link or web search ('open GitHub', 'show me the Iron Man wiki', "
        "'search for…', 'go to stark.com'). action: open (target = URL or search words; "
        "new_tab false to reuse the current tab), list (the open tabs), switch (index, "
        "1-based), close (index, default current), back, forward, reload, read (the text of "
        "the page currently shown — use it to answer questions about the page), show, hide "
        "(back to the HUD). Use browser_control only for automation in a separate browser "
        "(logging in to sites, filling forms, clicking through flows)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "open | list | switch | close | back | forward | reload | read | show | hide"},
            "target": {"type": "STRING", "description": "For open: a URL or search words."},
            "index": {"type": "NUMBER", "description": "For switch/close: tab number, 1-based."},
            "new_tab": {"type": "BOOLEAN", "description": "For open: false to load in the current tab."},
        },
        "required": ["action"],
    },
}

# Page text goes into the live conversation and stays there; every extra
# kilobyte makes the following replies slower. 3000 characters covers the
# gist of most pages, and a re-read of the same page soon after is refused.
_READ_LIMIT = 3000
_REREAD_S = 90.0
_last_read: dict = {"url": "", "at": 0.0}


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not HAVE_WEBENGINE:
        return ("The built-in browser needs PyQt6-WebEngine "
                "(pip install \"PyQt6-WebEngine>=6.11,<6.12\").")
    if player is None or not hasattr(player, "browser"):
        return "The built-in browser is not available here."
    action = str(parameters.get("action") or "open").lower().strip()
    idx = parameters.get("index")
    idx0 = None if idx in (None, "") else int(float(idx)) - 1      # 1-based for humans

    if action == "open":
        target = str(parameters.get("target") or "").strip()
        if not target:
            return "Tell me what to open — an address or what to search for."
        new_tab = parameters.get("new_tab")
        new_tab = True if new_tab is None else bool(new_tab)
        return player.browser("open", target=target, new_tab=new_tab)
    if action == "list":
        tabs = player.browser("list")
        if not isinstance(tabs, list) or not tabs:
            return "No browser tabs are open."
        return "Open tabs: " + "; ".join(
            f"{t['index'] + 1}. {t['title']}{' (showing)' if t['active'] else ''}" for t in tabs) + "."
    if action == "switch":
        if idx0 is None:
            return "Which tab number?"
        return player.browser("switch", index=idx0)
    if action == "close":
        return player.browser("close", index=idx0)
    if action in ("back", "forward", "reload", "show", "hide"):
        return player.browser(action)
    if action == "read":
        got = player.browser("read", timeout=10.0)
        if not isinstance(got, tuple):
            return str(got) or "No page is open."
        title, url, text = got
        if not url or url == "about:blank":
            return "No page is open in the browser."
        import time
        if url == _last_read["url"] and time.monotonic() - _last_read["at"] < _REREAD_S:
            ago = int(time.monotonic() - _last_read["at"])
            return (f"[ALREADY_READ] You were given the text of this page ({title}) {ago} s ago. "
                    f"Answer from that; do not read it again.")
        _last_read.update(url=url, at=time.monotonic())
        text = " ".join(text.split())
        more = " (truncated)" if len(text) > _READ_LIMIT else ""
        return (f"Page: {title} — {url}\n\n{text[:_READ_LIMIT]}{more}\n\n"
                f"This is the text of the page the user is looking at. Answer from it; do not read it out.")
    return f"Unknown browser action '{action}'."
