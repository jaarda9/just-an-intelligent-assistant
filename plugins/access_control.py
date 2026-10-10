"""
Access control — the voice front-end to core/access.py (guest mode).

"Lock down" switches to guest mode at once. "Unlock" never trusts the voice
(anyone in the room can say it): it checks the owner's face right now, or —
only if no face is enrolled — puts a confirm button on screen.
"""
from core import confirm
from core.access import get_guard
from core.presence import get_presence

PLUGIN = {
    "name": "access_control",
    "description": (
        "Guest mode / lockdown. action='lock' when the owner says 'lock down', "
        "'guest mode', 'someone is using my computer' — restricted tools (messages, "
        "files, automation, memory, protocols) are then refused until the owner is "
        "back. action='unlock' when asked to leave guest mode — this verifies the "
        "owner's face on the webcam (or asks for an on-screen confirmation if no "
        "face is enrolled); never assume it succeeded. action='status' to report."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"action": {"type": "STRING", "description": "lock | unlock | status"}},
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    guard = get_guard()
    action = str(parameters.get("action") or "status").lower().strip()

    if action == "lock":
        if not guard.enter_guest("locked down by the owner"):
            return "Guest mode is already on."
        return "Guest mode is on. Confirm in one short sentence."

    if action == "unlock":
        if not guard.guest:
            return "Guest mode is not on; nothing to unlock."
        verdict = get_presence().verify_owner()
        if verdict is True:
            guard.exit_guest("owner verified on the webcam")
            return "Owner verified; guest mode is off. Welcome them back briefly."
        if verdict is False:
            return ("[UNLOCK_REFUSED] The owner's face was not recognised, so guest mode "
                    "stays on. Say so in one short sentence; suggest facing the camera.")
        # No face enrolled / no camera: the on-screen gate, which the model cannot press.
        return confirm.request(
            "guest-unlock", "Leave guest mode",
            "Restores full access to messages, files, memory and protocols.",
            lambda: (guard.exit_guest("confirmed on screen"), "Guest mode off.")[1])

    since = ""
    if guard.guest and guard.since:
        import time
        since = f" for {int((time.time() - guard.since) // 60)} min"
    return (f"Guest mode is on{since} ({guard.reason})." if guard.guest
            else "Owner access — guest mode is off.")
