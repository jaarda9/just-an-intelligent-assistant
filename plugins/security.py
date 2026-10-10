"""
Security report — the voice front-end to core/security_watch.py.

The watcher itself runs in the background from main.py and raises alerts on
its own; this tool answers "who's on the network?", "any USB drives?", and
lets the user put a name to a device ("that's my phone").
"""
from core.security_watch import get_watch

PLUGIN = {
    "name": "security_report",
    "description": (
        "Security status of this computer and home network: which devices are on "
        "the local network (known and new), removable drives connected, and "
        "whether the background security watch is active. Use when the user asks "
        "who is on the network/Wi-Fi, about unknown devices, USB drives, or a "
        "security check. Use action='label' with device (IP or MAC) and name when "
        "the user identifies a device, e.g. 'that one is my phone'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "'report' (default) or 'label'."},
            "device": {"type": "STRING", "description": "For label: the device's IP or MAC address."},
            "name":   {"type": "STRING", "description": "For label: what to call it, e.g. 'Living room TV'."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    watch = get_watch()
    try:
        if str(parameters.get("action") or "report").lower().strip() == "label":
            device, name = parameters.get("device", ""), parameters.get("name", "")
            if not device or not name:
                return "To label a device I need its IP or MAC address and a name."
            return watch.label_device(device, name)
        report = watch.report()
    except Exception as e:
        return f"The security check failed: {e}"
    if player:
        try:
            player.show_content("SECURITY", report)
        except Exception:
            pass
    return (f"{report}\n\nThe full list is on the HUD. Summarise in one or two sentences "
            f"in the user's language: how many devices, and anything unnamed or new.")
