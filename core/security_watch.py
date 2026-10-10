"""
Security watch — the "Sir, an unfamiliar device has joined the network" layer.

Three cheap, local checks, polled from main.py's system-monitor loop:

  network  — new MAC addresses in this machine's ARP (neighbour) table.
             Known devices persist in config/known_devices.json, so a restart
             does not re-announce the household. The ARP table only lists
             devices this computer has exchanged traffic with, so this catches
             most active newcomers, not every silent one.
  drives   — a removable drive appearing (USB stick, SD card).
  process  — sustained high CPU from a program running out of Temp or
             Downloads, where legitimate long-running software rarely lives.

check() returns a [SYSTEM_ALERT] string or None, the same contract as
actions.system_monitor.SystemMonitor. Nothing here sends anything anywhere.
Disable with "security_watch_enabled": false in config/api_keys.json.
"""
from __future__ import annotations

import functools
import json
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil

_OS = platform.system()
_KNOWN_PATH = Path(__file__).resolve().parent.parent / "config" / "known_devices.json"

_NET_EVERY = 60.0         # seconds between ARP scans
_PROC_CPU = 40.0          # % of the whole machine
_PROC_STREAK = 3          # consecutive checks (~30 s at the 10 s loop)
_PROC_COOLDOWN = 1800.0

_MAC_RE = re.compile(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}", re.I)
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}


def _is_unicast(mac: str) -> bool:
    if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
        return False
    return not (int(mac[:2], 16) & 1)        # multicast bit (01:00:5e…, 33:33…)


def scan_arp() -> dict[str, str]:
    """{mac: ip} for unicast neighbours. Empty on any failure."""
    out: dict[str, str] = {}
    try:
        if _OS == "Linux" and Path("/proc/net/arp").exists():
            text = Path("/proc/net/arp").read_text()
        else:
            args = ["arp", "-a"] if _OS == "Windows" else ["arp", "-an"]
            text = subprocess.run(args, capture_output=True, text=True,
                                  timeout=8, **_HIDE).stdout
    except Exception:
        return out
    for line in text.splitlines():
        m, ip = _MAC_RE.search(line), _IP_RE.search(line)
        if not (m and ip):
            continue
        mac = m.group(0).lower().replace("-", ":")
        if _is_unicast(mac) and not ip.group(1).startswith(("224.", "239.", "255.")):
            out[mac] = ip.group(1)
    return out


def _removable() -> dict[str, str]:
    """{mountpoint: label-ish} for removable drives."""
    out = {}
    try:
        for part in psutil.disk_partitions(all=False):
            opts = part.opts.lower()
            if "removable" in opts or part.mountpoint.startswith(("/media/", "/run/media/", "/Volumes/")):
                out[part.mountpoint] = part.fstype or "drive"
    except Exception:
        pass
    return out


@functools.lru_cache(maxsize=1024)
def _canon(path: str) -> str:
    # realpath expands Windows 8.3 short names (C:\Users\ABC~1\…), which is
    # how %TEMP% is often stored, while process paths come back long-form.
    return os.path.normcase(os.path.realpath(path))


def _risky_dirs() -> tuple[str, ...]:
    dirs = {os.environ.get("TEMP"), os.environ.get("TMP"), "/tmp",
            str(Path.home() / "Downloads")}
    return tuple(_canon(d) + os.sep for d in dirs if d)


# This app may itself live in Downloads (a fresh clone usually does); its own
# interpreter and helpers must never be reported as a suspicious process.
_APP_ROOT = _canon(str(Path(__file__).resolve().parent.parent)) + os.sep


class SecurityWatch:
    def __init__(self):
        self._lock = threading.Lock()
        self._known: dict[str, dict] = self._load_known()
        self._last_net = 0.0
        self._drives = _removable()            # present at launch: not news
        self._streak: dict[int, int] = {}
        self._proc_alerted: dict[str, float] = {}
        self._risky = _risky_dirs()
        self._own_pid = os.getpid()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load_known(self) -> dict:
        try:
            return json.loads(_KNOWN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_known(self) -> None:
        try:
            _KNOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
            _KNOWN_PATH.write_text(json.dumps(self._known, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Security] could not save known devices: {e}")

    # ── public ───────────────────────────────────────────────────────────────
    def enabled(self) -> bool:
        try:
            from memory.config_manager import load_api_keys
            return bool(load_api_keys().get("security_watch_enabled", True))
        except Exception:
            return True

    def check(self) -> str | None:
        if not self.enabled():
            return None
        alerts = [a for a in (self._check_network(), self._check_drives(),
                              self._check_processes()) if a]
        return " ".join(alerts) if alerts else None

    def label_device(self, mac_or_ip: str, name: str) -> str:
        key = mac_or_ip.strip().lower().replace("-", ":")
        with self._lock:
            for mac, info in self._known.items():
                if key in (mac, info.get("ip")):
                    info["name"] = name.strip()
                    self._save_known()
                    return f"Device {mac} ({info.get('ip')}) is now labelled '{name.strip()}'."
        return f"No known device matches '{mac_or_ip}'."

    def report(self) -> str:
        live = scan_arp()
        with self._lock:
            self._merge(live, alert=False)
            rows = []
            for mac, info in sorted(self._known.items(), key=lambda kv: kv[1].get("ip", "")):
                state = "online" if mac in live else "offline"
                rows.append(f"{info.get('name') or 'unnamed'} — {info.get('ip')} — {mac} — {state} "
                            f"— first seen {info.get('first_seen', '?')}")
        drives = _removable()
        lines = [f"NETWORK: {len(live)} device(s) visible now, {len(rows)} known."] + rows
        lines.append("REMOVABLE DRIVES: " + (", ".join(drives) if drives else "none"))
        lines.append("WATCH: " + ("active" if self.enabled() else "disabled in config"))
        return "\n".join(lines)

    # ── checks ───────────────────────────────────────────────────────────────
    def _merge(self, live: dict[str, str], alert: bool) -> list[tuple[str, str]]:
        """Fold a scan into the known list; return the newcomers."""
        first_run = not self._known
        new = []
        stamp = time.strftime("%Y-%m-%d %H:%M")
        for mac, ip in live.items():
            if mac not in self._known:
                self._known[mac] = {"ip": ip, "first_seen": stamp, "name": ""}
                if alert and not first_run:
                    new.append((mac, ip))
            else:
                self._known[mac]["ip"] = ip
        if live:
            self._save_known()
        return new

    def _check_network(self) -> str | None:
        now = time.monotonic()
        if now - self._last_net < _NET_EVERY:
            return None
        self._last_net = now
        live = scan_arp()
        if not live:
            return None
        with self._lock:
            new = self._merge(live, alert=True)
        if not new:
            return None
        desc = ", ".join(f"{ip} ({mac})" for mac, ip in new[:3])
        return (f"[SYSTEM_ALERT] Security: {len(new)} unfamiliar device(s) just appeared on the "
                f"local network: {desc}. Inform the user calmly in their language, in one or two "
                f"sentences, and mention they can ask you to label it if they recognise it.")

    def _check_drives(self) -> str | None:
        now = _removable()
        added = [m for m in now if m not in self._drives]
        self._drives = now
        if not added:
            return None
        return (f"[SYSTEM_ALERT] Security: a removable drive was just connected at "
                f"{', '.join(added)}. Mention it briefly in the user's language.")

    def _check_processes(self) -> str | None:
        ncpu = psutil.cpu_count() or 1
        seen = set()
        hit = None
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                exe = p.info.get("exe") or ""
                pid = p.info["pid"]
                if not exe or pid == self._own_pid:
                    continue
                cexe = _canon(exe)
                if not cexe.startswith(self._risky) or cexe.startswith(_APP_ROOT):
                    continue
                seen.add(pid)
                cpu = p.cpu_percent(None) / ncpu
                self._streak[pid] = self._streak.get(pid, 0) + 1 if cpu >= _PROC_CPU else 0
                if self._streak[pid] >= _PROC_STREAK and hit is None:
                    last = self._proc_alerted.get(exe, 0.0)
                    if time.monotonic() - last > _PROC_COOLDOWN:
                        self._proc_alerted[exe] = time.monotonic()
                        hit = (p.info.get("name") or "?", exe, cpu)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for pid in list(self._streak):
            if pid not in seen:
                del self._streak[pid]
        if not hit:
            return None
        name, exe, cpu = hit
        return (f"[SYSTEM_ALERT] Security: '{name}' has been using about {cpu:.0f}% of the CPU "
                f"for over half a minute, running from {exe}. Programs in that folder are "
                f"usually temporary or freshly downloaded. Tell the user calmly in their language "
                f"and suggest they check it if they do not recognise it.")


_instance: SecurityWatch | None = None
_inst_lock = threading.Lock()


def get_watch() -> SecurityWatch:
    """Process-wide singleton, shared by main.py's monitor loop and the
    security_report plugin."""
    global _instance
    with _inst_lock:
        if _instance is None:
            _instance = SecurityWatch()
        return _instance
