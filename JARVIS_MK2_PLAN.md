# J.A.R.V.I.S. — Mark II build plan

Mark I (`JARVIS_PLAN.md`) gave the app a personality, protocols, diagnostics, sound,
a boot sequence, rings, telemetry, a security watch and webcam presence. Mark II
rebuilds the suit around it: faster, a completely new interface, more ways in, more
reach, and nothing that breaks quietly.

Every suit is versioned. Each Mark below ships on its own, is tested before the next
one starts, and is committed to git so any step can be rolled back.

---

## Where we start (measured 2026-10-10)

| Metric | Now | Mark II target |
|---|---|---|
| Idle CPU (setup screen, software-rendered face) | 3.9% of 8 cores (≈ ⅓ of one core) | < 1% |
| RAM | 167 MB | ≤ 180 MB with the new UI |
| `ui.py` | 5,389 lines, one file, 20 classes | split into a `ui/` package, no file > 1,200 lines |
| Automated tests | none (my scratch scripts only) | `tests/` folder, one command runs all |
| Version control | none | git, one commit per step |
| Ways to talk to it | desktop window, phone dashboard | + tray, mini-mode, global summon, CLI, optional Telegram |

---

## Mark II — Foundations and efficiency
*First, because everything after it gets faster and safer to change.*

| # | Item | Detail |
|---|---|---|
| 2.1 | **Git + checkpoints** | `git init` locally (nothing pushed anywhere). Commit the current state as the baseline, then one commit per item. Uses the fixed `.gitignore`, so keys and face data stay out. |
| 2.2 | **Test suite** | Move my scratch tests into `tests/`: plugins, protocols, security watch, presence logic, offscreen HUD renders compared against reference images. `python -m pytest` runs them all. |
| 2.3 | **GPU-backed rendering** | Draw the HUD through OpenGL (`QOpenGLWidget`) instead of the CPU raster engine. Same drawing code, the graphics card does the work. Automatic fallback to software rendering if OpenGL isn't available. |
| 2.4 | **Smarter frame pacing** | 60 fps only while speaking or animating; 10 fps when idle; 0 when minimised or covered. Measured before and after. |
| 2.5 | **Faster startup** | Time every import at launch; defer heavy ones (Playwright, PDF, Office, OpenCV) until first use. Target: window on screen in under 1.5 s. |
| 2.6 | **Split `ui.py`** | Into `ui/theme.py`, `ui/hud/`, `ui/panels/`, `ui/overlays/`, `ui/window.py`. Pure move, no behaviour change, verified by the render tests from 2.2. This is what makes the redesign safe. |
| 2.7 | **Local log + crash report** | Rotating `logs/jarvis.log`; an uncaught error writes a short report and JARVIS says what failed instead of freezing. |

---

## Mark III — The new interface
*The face goes. JARVIS was never a face; he was light, data and a voice.*

### 3.1 New centrepiece (you choose; the others stay selectable in ⚙)
| Concept | What it is |
|---|---|
| **A · Holo-Sphere** | A 3D globe of ~2,000 glowing points, slowly rotating. Speaking sends ripples across its surface tied to the real voice; thinking spins it up and draws orbiting data streams; listening makes it breathe. Closest to JARVIS in *Avengers*. |
| **B · Arc Reactor Mk II** | The existing reactor style, rebuilt: depth layers, light bloom, triangular core, particles drawn in toward the centre while thinking. Most "Iron Man". |
| **C · Voice Ring** | Minimal. A single luminous ring that bends with the voice, plus thin orbit lines. Calm and elegant; the ring is the whole show. Closest to *Iron Man 3*. |

All three: state colours (blue idle, green listening, gold thinking, white speaking, red alert), GPU-drawn, under 1% CPU idle.

### 3.2 Window and layout
- **Frameless window** with a custom title bar, so no Windows chrome breaks the illusion. Drag, snap, minimise and full-screen still work.
- **Glass panels**: translucent, thin glowing borders, corner brackets, subtle scan-line texture.
- **Hex/circuit backdrop** replacing the dot grid, slowly animated, dimmed behind panels.
- **Typography**: one HUD font family bundled with the app (open licence, e.g. Rajdhani/Orbitron under SIL OFL) instead of Courier New.
- **Modular side docks**: panels slide in and out and can be re-ordered: Systems, Network & Security, Protocols, Weather, Calendar, Media, Activity log, Files.
- **In-HUD notifications**: toasts that slide in from the edge for alerts, finished tasks and security events.
- **Animated transitions** everywhere: panels, overlays and state changes ease in and out, nothing pops.

### 3.3 Mini-mode
A small always-on-top orb in a screen corner while you work in other apps. It glows with state, pulses when speaking, shows toasts beside it, and expands to the full HUD on click or hotkey.

### 3.4 Themes
**Stark Blue** (default) · **Mark III** (red and gold) · **Stealth** (graphite and white) · plus the existing hue wheel for custom colours. The centrepiece, panels and sounds follow the theme.

### 3.5 Boot sequence v2
Rebuilt for the new centrepiece: the sphere or reactor assembles from points, panels fly in one by one with their checklists, and the tone resolves when the last system is online.

---

## Mark IV — More ways in (access points)

| # | Item | Detail |
|---|---|---|
| 4.1 | **System tray** | Icon with live state colour; menu: show/hide, mute, protocols, presence on/off, quit. Closing the window can minimise to tray. |
| 4.2 | **Global summon hotkey** | One key combination brings JARVIS to the front (or toggles mini-mode) from any app. Push-to-talk (Ctrl+Space) stays. |
| 4.3 | **Phone dashboard redesign** | The existing phone dashboard (login, commands, phone mic, file upload) gets the new look plus live status, diagnostics gauges, protocol buttons and the security feed. Its security is audited as part of the work: login, tokens, TLS. |
| 4.4 | **Command line** | `jarvis "run work protocol"` from any terminal sends the command to the running instance over a local-only, token-protected channel. Good for scripts and shortcuts. |
| 4.5 | **Access levels** | Uses presence: when the webcam sees someone who isn't you and you're away, JARVIS switches to **guest mode**. In guest mode, sending messages, deleting or moving files, shutdown, settings changes and protocols are refused until you're back or you confirm. |
| 4.6 | **Telegram bridge** *(optional)* | Talk to JARVIS from anywhere through a private Telegram bot that only answers your account. Needs a bot token from you. |

---

## Mark V — More reach (capabilities)

| # | Item | Detail | Needs from you |
|---|---|---|---|
| 5.1 | **Protocol editor in the HUD** | Build, edit and test protocols from the interface instead of JSON: pick tools from a list, fill in fields, reorder steps. | — |
| 5.2 | **Protocol triggers** | Run protocols automatically: on a schedule ("weekdays 09:00 → work"), when you sit down (presence), when you leave, on a hotkey. | — |
| 5.3 | **Media control + Now Playing** | Play, pause, skip and volume for any player through the system media keys; a Now Playing panel with title and artist where Windows exposes it. | — |
| 5.4 | **Smart home** | One adapter interface, three back-ends: Tuya/Smart Life (`tinytuya`, already installed), Philips Hue, Home Assistant. "Dim the lights", "kill the lights", and protocol steps such as "house party → lights to party mode". | Brand and access details |
| 5.5 | **Calendar + Gmail** | "You have a meeting in 20 minutes", "three unread from your boss"; Calendar and Mail panels in the HUD. | Google sign-in setup (one time, guided) |
| 5.6 | **Briefing v2** | The morning briefing combines time, weather, calendar, unread mail, system health and overnight security events into one spoken summary plus a briefing panel. | 5.5 for mail and calendar |
| 5.7 | **Task tracker panel** | Long jobs (dev agent, downloads, protocols, searches) show live progress in a panel, and JARVIS reports when each finishes. | — |

---

## Mark VI — Reliability and polish

| # | Item | Detail |
|---|---|---|
| 6.1 | **Connection resilience** | Clear HUD state for "offline" and "reconnecting"; local commands (protocols, volume, apps, diagnostics) keep working from the text box while Gemini is unreachable. |
| 6.2 | **Settings consolidation** | One Settings overlay with tabs (Interface, Voice, Sounds, Security, Presence, Access, Plugins) instead of hand-editing `api_keys.json` for the new switches. |
| 6.3 | **Performance pass** | Profile a 30-minute session: CPU, RAM, response latency. Fix whatever the profile shows. |
| 6.4 | **Documentation** | `README` section for everything added, plus an in-app "What can you do?" panel generated from the live tool list. |

---

## Order and size

| Mark | Size | Depends on |
|---|---|---|
| II Foundations | Medium | — |
| III Interface | **Large** (the biggest piece) | II (split UI, GPU rendering, render tests) |
| IV Access | Medium | III for the visuals; 4.5 uses presence (done) |
| V Capabilities | Medium–Large | 5.4 and 5.5 need your answers; the rest can start any time |
| VI Reliability | Small–Medium | everything above |

Each Mark ends with a working app, a test run, before/after numbers where it's
about speed, and screenshots where it's about looks.

---

## Decisions (2026-10-10)
1. **Centrepiece:** A · Holo-Sphere (B and C still built as selectable alternatives; face kept as a legacy option).
2. **Default theme:** Stark Blue.
3. **Smart home:** none for now. 5.4 is deferred; the adapter interface can be added later.
4. **Google Calendar + Gmail:** yes. 5.5 and the full Briefing v2 (5.6) are in scope; guided Google setup when we get there.
5. **Telegram bridge:** no. 4.6 is dropped.
