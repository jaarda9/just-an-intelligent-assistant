"""
jarvis — talk to the running JARVIS from any terminal.

    jarvis "what's the weather like"     send a command, as if typed in the HUD
    jarvis --protocol work               run a protocol directly (no model round trip)
    jarvis --status                      state, access level, microphone
    jarvis --summon                      bring the HUD to the front

Standard library only. Connects to the local channel the app opens on
127.0.0.1 (core/cli_server.py) using the token in config/cli.json.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

INFO = Path(__file__).resolve().parent / "config" / "cli.json"


def send(req: dict) -> dict:
    try:
        info = json.loads(INFO.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "result": "JARVIS is not running (no config/cli.json)."}
    req["token"] = info["token"]
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5) as s:
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8") or "{}")
    except (ConnectionRefusedError, socket.timeout, OSError):
        return {"ok": False, "result": "JARVIS is not answering (is it running?)."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis", description="Talk to the running JARVIS.")
    ap.add_argument("text", nargs="*", help="command to send, as if typed in the HUD")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--protocol", metavar="NAME", help="run a protocol directly")
    g.add_argument("--status", action="store_true", help="show state and access level")
    g.add_argument("--summon", action="store_true", help="bring the HUD to the front")
    a = ap.parse_args(argv)

    if a.protocol:
        req = {"cmd": "protocol", "text": a.protocol}
    elif a.status:
        req = {"cmd": "status"}
    elif a.summon:
        req = {"cmd": "summon"}
    elif a.text:
        req = {"cmd": "say", "text": " ".join(a.text)}
    else:
        ap.print_help()
        return 2
    resp = send(req)
    print(resp.get("result", ""))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
