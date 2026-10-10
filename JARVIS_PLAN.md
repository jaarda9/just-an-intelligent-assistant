# Making MARK LV feel like J.A.R.V.I.S.

Everything below goes in as new plugins (`plugins/*.py`) or small, contained
edits, so upstream MARK LV updates stay easy to merge.

## Phase 1: Personality, protocols, diagnostics  ✓
| # | Item | Where | Status |
|---|------|-------|--------|
| 1.1 | British-butler persona: formal, unflappable, dry wit, film-style phrasing ("As you wish", "Shall I…") | `core/prompt.txt` `[VOICE]` | done |
| 1.2 | `run_tool` hook so a plugin can run other tools in order, deterministically | `main.py` (`_run_tool_sync`) | done |
| 1.3 | **Protocols**: named multi-step routines spoken by name ("initiate work protocol"), defined in `config/protocols.json` | `plugins/protocols.py` | done |
| 1.4 | **Diagnostics**: full system readout (CPU/GPU/RAM/temps/disks/network/battery/top processes) shown as a HUD panel with a spoken verdict | `plugins/diagnostics.py` | done |

## Phase 2: Presence (sound and boot)  ✓
| # | Item | Where | Status |
|---|------|-------|--------|
| 2.1 | Sound pack: wake chirp, tool-start tick, task-done tone, sleep glide, alert tone (synthesised, no copyrighted audio). Off switch: `"sfx_enabled": false` in `config/api_keys.json` | `core/sfx.py`, `ui._apply_state`, `main._run_system_monitor` | done |
| 2.2 | Boot sequence: veil lift, scan ring and scan line, ticking systems checklist, timed to a boot tone | `ui.HudCanvas._paint_boot` | done |
| 2.3 | Deepest/calmest Gemini voice as default | already `Charon` upstream | no change needed |

## Phase 3: Arc-reactor HUD  ✓ (3.2: corner sparklines + T+ clock; 3.3: ring gauges via `JarvisUI.show_diagnostics`)
| # | Item | Where |
|---|------|-------|
| 3.1 | Rotating concentric rings around the face, speed tied to state (idle/listening/thinking/speaking). Note: upstream already ships a full reactor-core HUD as an alternative to the face (⚙ → HUD style) | `ui.HudCanvas._paint_face_rings` ✓ |
| 3.2 | Hex-grid backdrop + live telemetry ticker (CPU/RAM/net) along the HUD edge | `ui.py` |
| 3.3 | Animated diagnostics panel (gauges instead of text) | `ui.py`, fed by `plugins/diagnostics.py` |

## Phase 4: Beyond the PC
| # | Item | Needs from you |
|---|------|----------------|
| 4.1 | Smart lights/plugs: Tuya (`tinytuya`, already installed) or Home Assistant (MQTT) | Device brand, local keys or HA URL + token |
| 4.2 | Protocol steps for smart-home actions ("house party protocol" → lights) | 4.1 |
| 4.3 | Google Calendar + Gmail briefing ("meeting in 20 minutes, three unread from…") | Google Cloud OAuth client (one-time setup) |

## Phase 5: Awareness and security
| # | Item | Notes | Status |
|---|------|-------|--------|
| 5.1 | Owner recognition on webcam: welcome back after 5+ min away; alert on an unknown face while away. Say "learn my face" to enrol, "forget my face" to delete | `core/presence.py`, `plugins/presence.py`; YuNet + SFace (hash-pinned download); stores a 128-number embedding only, never a photo; off by default | done |
| 5.2 | Network watch: alert on a new device joining the LAN; "who's on the network?"; label devices by voice | `core/security_watch.py`, `plugins/security.py`; known list in `config/known_devices.json` | done |
| 5.3 | USB watch: alert when a removable drive is connected | same module | done |
| 5.4 | Suspicious-process alert: sustained ≥40% CPU for ~30 s from a program in Temp or Downloads | same module; the app itself is excluded | done |

Security alerts are held until a quiet moment (not dropped mid-conversation).
Off switch: `"security_watch_enabled": false` in `config/api_keys.json`.

## Fixes to upstream found along the way
- `.gitignore` used end-of-line comments, which git does not support, so its
  secret rules matched nothing: `config/api_keys.json` (the Gemini key),
  TLS keys and the WhatsApp session would all have been committed. Rewritten
  with comments on their own lines and verified with `git check-ignore`.

## Defining a protocol
Edit `config/protocols.json` (created with examples on first use). Each step is
any tool JARVIS has, with its arguments, plus an optional `wait` in seconds:

```json
"work": {
  "aliases": ["work mode", "focus"],
  "announce": "Work protocol engaged.",
  "steps": [
    {"tool": "open_app", "args": {"app_name": "Visual Studio Code"}},
    {"tool": "computer_settings", "args": {"action": "volume_set", "value": "25"}},
    {"wait": 1}
  ]
}
```
Restart is not needed: the file is re-read on every call.
