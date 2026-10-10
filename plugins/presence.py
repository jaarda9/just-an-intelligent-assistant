"""
Presence — voice controls for core/presence.py (webcam owner recognition).

"Learn my face" enrols, "turn on presence" enables the background check,
"forget my face" deletes the stored embedding and turns it off.
"""
from core.presence import get_presence, models_ready

PLUGIN = {
    "name": "presence",
    "description": (
        "Webcam presence: recognises the owner returning to the desk (to welcome "
        "them back) and notices an unknown person at the computer while they are "
        "away. Opt-in and local. Actions: 'enroll' when the user says 'learn my "
        "face' / 'remember what I look like' (they must face the camera for ~3 s; "
        "first time downloads a 37 MB model); 'enable' / 'disable' to turn the "
        "background check on or off; 'status'; 'forget' to delete their face data."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "enroll | enable | disable | status | forget"},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    p = get_presence()
    action = str(parameters.get("action") or "status").lower().strip()

    def log(msg):
        if player:
            try:
                player.write_log(f"SYS: {msg}")
            except Exception:
                pass

    try:
        if action == "enroll":
            if player and hasattr(player, "request_say"):
                first = "" if models_ready() else " The first time takes a minute to download the recognition model."
                player.request_say(
                    "[TOOL_STARTING] Tell the user in one short sentence to look straight "
                    f"at the camera for a few seconds.{first}")
            result = p.enroll(log=log)
            if result.startswith("Face enrolled") and not p.enabled():
                result += " " + p.set_enabled(True)
            return result + " Confirm briefly; mention they can say 'forget my face' any time."
        if action == "enable":
            return p.set_enabled(True)
        if action == "disable":
            return p.set_enabled(False)
        if action == "forget":
            return p.forget()
        return p.status()
    except Exception as e:
        return f"Presence failed: {e}"
