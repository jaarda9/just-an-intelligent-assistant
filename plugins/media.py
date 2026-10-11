"""
Media — play/pause/skip whatever is playing, and say what it is.
Front-end to core/media.py.
"""
from core import media

PLUGIN = {
    "name": "media_control",
    "description": (
        "Controls whatever is ALREADY playing in any app (Spotify, a browser tab, VLC, …) "
        "and reports what it is. action: play_pause, play (= RESUME the paused item, "
        "never a new one), pause, next, previous, stop, or now_playing (\"what's this "
        "song?\"). Use for 'pause', 'resume', 'next track', 'skip', 'what's playing'. "
        "When the user names something to play ('play Elvis Presley', 'play some jazz', "
        "'play the Dune trailer') do NOT use this — use video_player, which finds it "
        "and plays it on the HUD."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"action": {"type": "STRING",
                                  "description": "play_pause | play | pause | next | previous | stop | now_playing"}},
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action") or "now_playing").lower().strip()
    if action == "now_playing":
        np = media.now_playing()
        if not np or not np.get("title"):
            return "Nothing is playing right now."
        artist = f" by {np['artist']}" if np["artist"] else ""
        return f"{np['state'].title()}: '{np['title']}'{artist}, in {np['app']}."
    return media.control(action)
