"""
Diagnostics — a full, suit-style systems check.

Builds on actions.system_monitor.get_system_status() (CPU, RAM, GPU, CPU temp,
uptime) and adds disks, live network throughput, battery and the busiest
processes. The readout goes to the HUD's content panel; the model gets the same
numbers plus a verdict line so it can deliver a one-breath status report.
"""
import time

import psutil

from actions.system_monitor import get_system_status

# Above these a component is reported as needing attention, not as nominal.
_WARN = {"cpu": 85.0, "ram": 85.0, "gpu": 90.0, "temp": 80.0, "disk": 90.0, "battery": 20.0}
_SAMPLE_SECS = 0.6

PLUGIN = {
    "name": "run_diagnostics",
    "description": (
        "Runs a FULL systems diagnostic and shows it on the HUD: CPU, GPU, RAM, "
        "temperature, every disk, network throughput, battery and the busiest "
        "processes, each marked nominal or needing attention. Use when the user "
        "says 'run diagnostics', 'system check', 'status report', 'how are we "
        "doing' about the computer. For one quick number (just CPU, just RAM) "
        "use system_status instead."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}


def _bar(pct: float, width: int = 14) -> str:
    filled = int(round(max(0.0, min(pct, 100.0)) / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _rate(n_bytes: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if n_bytes < 1024:
            return f"{n_bytes:.0f} {unit}" if unit == "B/s" else f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB/s"


def _disks() -> list[tuple[str, float, float]]:
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append((part.mountpoint, u.percent, u.free / 1024 ** 3))
    return out


def _sample_net_and_procs():
    """One shared sampling window for network rate and per-process CPU."""
    procs = []
    for p in psutil.process_iter(["name"]):
        try:
            p.cpu_percent(None)   # prime
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    n0 = psutil.net_io_counters()
    time.sleep(_SAMPLE_SECS)
    n1 = psutil.net_io_counters()

    ncpu = psutil.cpu_count() or 1
    usage: dict[str, float] = {}
    for p in procs:
        try:
            name = p.info.get("name") or "?"
            if name.lower() in ("system idle process", "idle"):
                continue
            usage[name] = usage.get(name, 0.0) + p.cpu_percent(None) / ncpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    top = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)[:5]
    down = (n1.bytes_recv - n0.bytes_recv) / _SAMPLE_SECS
    up = (n1.bytes_sent - n0.bytes_sent) / _SAMPLE_SECS
    return down, up, top


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        s = get_system_status()
        down, up, top = _sample_net_and_procs()
        disks = _disks()
        try:
            batt = psutil.sensors_battery()
        except Exception:
            batt = None
    except Exception as e:
        return f"Diagnostics could not complete: {e}"

    warnings: list[str] = []
    lines = ["SYSTEMS DIAGNOSTIC", ""]

    def row(label: str, pct, detail: str, key: str, invert: bool = False):
        if pct is None:
            lines.append(f"{label:<6} {'—':<14}  {detail}")
            return
        bad = pct <= _WARN[key] if invert else pct >= _WARN[key]
        flag = "⚠" if bad else "✓"
        if bad:
            warnings.append(f"{label} {pct:.0f}%")
        lines.append(f"{label:<6} {_bar(pct)} {pct:5.1f}%  {detail} {flag}")

    row("CPU", s["cpu_percent"], "", "cpu")
    row("GPU", s["gpu_percent"], "" if s["gpu_percent"] is not None else "no NVIDIA telemetry", "gpu")
    row("RAM", s["ram_percent"], f"{s['ram_used_gb']}/{s['ram_total_gb']} GB", "ram")
    temp = s["cpu_temp_c"]
    if temp is None:
        lines.append(f"{'TEMP':<6} {'—':<14}  sensor not exposed")
    else:
        bad = temp >= _WARN["temp"]
        if bad:
            warnings.append(f"CPU temperature {temp:.0f}°C")
        lines.append(f"{'TEMP':<6} {temp:.0f}°C {'⚠' if bad else '✓'}")

    lines.append("")
    for mount, pct, free_gb in disks:
        row(mount.rstrip("\\/") or mount, pct, f"{free_gb:.0f} GB free", "disk")

    lines.append("")
    lines.append(f"NET    ↓ {_rate(down)}   ↑ {_rate(up)}")
    if batt is not None:
        state = "charging" if batt.power_plugged else "on battery"
        row("BATT", float(batt.percent), state, "battery", invert=True)
    lines.append(f"UPTIME {s['uptime']}   PROCESSES {s['process_count']}")

    if top:
        lines += ["", "TOP PROCESSES (CPU)"]
        lines += [f"  {name[:28]:<28} {pct:5.1f}%" for name, pct in top]

    verdict = ("All systems nominal." if not warnings
               else "Attention required: " + ", ".join(warnings) + ".")
    lines += ["", verdict]
    panel = "\n".join(lines)

    gauges = [("CPU", s["cpu_percent"], _WARN["cpu"], False),
              ("GPU", s["gpu_percent"], _WARN["gpu"], False),
              ("RAM", s["ram_percent"], _WARN["ram"], False)]
    if disks:
        fullest = max(disks, key=lambda d: d[1])
        gauges.append((f"DISK {fullest[0].rstrip(chr(92) + '/')}", fullest[1], _WARN["disk"], False))
    if batt is not None:
        gauges.append(("BATT", float(batt.percent), _WARN["battery"], True))

    if player:
        try:
            if hasattr(player, "show_diagnostics"):
                player.show_diagnostics(gauges)
            player.show_content("DIAGNOSTICS", panel)
            player.write_log(f"JARVIS: Diagnostics — {verdict}")
            if hasattr(player, "notify"):
                player.notify("Diagnostics", verdict, "alert" if warnings else "ok")
        except Exception:
            pass

    busiest = f" Busiest process: {top[0][0]} at {top[0][1]:.0f}% CPU." if top else ""
    return (
        f"{panel}\n\n"
        f"The full readout is already on the HUD. Give the user a two-sentence "
        f"status report in their language: the verdict first, then the one "
        f"figure that matters most.{busiest}"
    )
