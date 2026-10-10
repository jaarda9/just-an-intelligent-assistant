"""
Local command channel for the `jarvis` terminal command (jarvis_cli.py).

  * Listens on 127.0.0.1 only — never reachable from the network.
  * A fresh random token per launch, written with the port to
    config/cli.json (git-ignored) and deleted on exit. Only processes that can
    read your user files can talk to JARVIS this way.
  * One JSON line in, one JSON line out; requests are size-capped and timed out.

The handler decides what each command does; everything it runs still goes
through the normal dispatcher, guest-mode checks included.
"""
from __future__ import annotations

import atexit
import hmac
import json
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import Callable

INFO_PATH = Path(__file__).resolve().parent.parent / "config" / "cli.json"
_MAX = 8192


class CLIServer:
    def __init__(self, handler: Callable[[dict], dict]):
        self._handler = handler
        self._token = secrets.token_hex(32)
        self._sock: socket.socket | None = None
        self.port = 0

    def start(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))           # loopback only, OS-chosen port
        s.listen(4)
        self._sock, self.port = s, s.getsockname()[1]
        INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        INFO_PATH.write_text(json.dumps({"port": self.port, "token": self._token,
                                         "pid": os.getpid()}), encoding="utf-8")
        atexit.register(self.stop)
        threading.Thread(target=self._accept, name="cli-server", daemon=True).start()
        return self.port

    def stop(self) -> None:
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        try:
            info = json.loads(INFO_PATH.read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                INFO_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    def _accept(self) -> None:
        while True:
            try:
                conn, addr = self._sock.accept()
            except OSError:
                return                          # socket closed
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5.0)
            try:
                buf = b""
                while b"\n" not in buf and len(buf) <= _MAX:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    buf += chunk
                if len(buf) > _MAX:
                    raise ValueError("request too large")
                req = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
                if not hmac.compare_digest(str(req.get("token", "")), self._token):
                    resp = {"ok": False, "result": "bad token"}
                else:
                    resp = self._handler(req)
            except Exception as e:
                resp = {"ok": False, "result": f"bad request: {e}"}
            try:
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            except Exception:
                pass
