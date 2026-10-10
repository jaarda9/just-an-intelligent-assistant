"""
Media — play/pause/skip whatever is playing, and say what it is.
Front-end to core/media.py.
"""
from core import media

PLUGIN = {
    "name": "media_control",
    "description": (
        "Controls the music or video currently playing in ANY app (Spotify, a "
        "browser tab, VLC, …) and reports what is playing. action: play_pause, "
        "play, pause, next, previous, stop, or now_playing (\"what's this song?\"). "
        "Use this for 'pause the music', 'next track', 'skip', 'what's playing'. "
        "To START something new (a song, a video) use youtube_video or open_app instead."
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
