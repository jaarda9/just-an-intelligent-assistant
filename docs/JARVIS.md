# J.A.R.V.I.S. — user guide

This build extends **MARK LV by FatihMakes** with a new interface, more ways to
reach the assistant, protocols, security features and Google integration.
Everything runs on your PC; the only thing sent to the internet is the
conversation with Gemini (and, if you connect it, read-only Google requests).

![The HUD](screenshots/mark3-listening.png)

---

## 1. Install and start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe setup.py      # dependencies + browser engine
.\.venv\Scripts\python.exe main.py
```

Use the `.venv` copy of Python. On Microsoft Store Python, installing into
the global site-packages fails on Windows' path-length limit.

On first launch, paste your **free Gemini API key** into the setup screen.
It is stored in `config/api_keys.json` in plain text, so treat that file like
a password.

---

## 2. The interface

| Area | What it shows |
|---|---|
| **Centre** | The **Holo-Sphere**: blue when idle, green when listening, gold with orbiting streams when thinking, rippling when speaking, red when offline. ⚙ → HUD style (or System Settings) switches to the Voice Ring, Reactor core or the legacy face. |
| **SYSTEMS** | CPU, memory, network, GPU and temperature. |
| **STATUS** | Voice link, security watch, presence and access level, all live. |
| **AGENDA** | Your next events, once Google is connected. |
| **NOW PLAYING** | Whatever any app is playing, with ◀◀ ❚❚ ▶▶ controls. |
| **COMMS** | The conversation and system messages. |
| **TASKS** | Jobs that take more than a moment, with progress. |
| **COMMAND** | Type a request, drop a file, interrupt, mute. |

Notifications slide in at the top right. **F9** shrinks JARVIS to a small orb
that stays on top while you work.

**Themes:** ⚙ → Customise → Stark Blue, Mark III (red and gold) or Stealth
(graphite), or pick any colour on the wheel.

---

## 3. Keys and shortcuts

| Keys | Action |
|---|---|
| **Ctrl+Alt+J** | Summon JARVIS from any app (press again to shrink to the orb) |
| **Ctrl+Space** (hold) | Push-to-talk, if enabled |
| **F4** | Mute / unmute the microphone |
| **F9** | Mini-mode |
| **F11** | Fullscreen |
| **Esc** | Interrupt JARVIS mid-sentence |

Drag the header to move the window; double-click it to maximise. The tray icon
(coloured by state) has the same everyday actions.

---

## 4. Things to say

- *"Run diagnostics"*: full system check with gauges on the HUD.
- *"Initiate work protocol"*, *"good night protocol"*: run a protocol.
- *"Pause the music"*, *"next track"*, *"what's playing?"*
- *"Who's on the network?"*, *"192.168.1.15 is my phone"*
- *"What's on my calendar?"*, *"any new emails?"* (Google, read-only)
- *"Learn my face"*, *"turn on presence"*, *"forget my face"*
- *"Lock down"*: guest mode (see §7)

⚙ → **What can you do?** lists every capability of your running copy.

---

## 5. Protocols

A protocol is a named routine of steps, such as *"work"*: set the volume, open
VS Code, start Spotify.

- **Edit:** 🎛 → *Protocols — edit & schedule* (or tray → *Edit protocols…*).
  Pick a tool for each step, fill in its fields, add waits, reorder, then
  **Save** and **Test run**.
- **Triggers:** run a protocol automatically at a time on chosen days, when
  you sit down or leave (needs presence), or when JARVIS starts.
- **Run it** by voice, from the tray, from the phone, or with
  `jarvis --protocol work`.

Protocols live in `config/protocols.json`.

---

## 6. More ways in

- **Tray icon:** open, mini-mode, mute, protocols, presence, settings, quit.
- **Terminal:** run these from the JARVIS folder (or add the folder to PATH):
  ```
  jarvis "what's the weather"
  jarvis --protocol work
  jarvis --status
  jarvis --summon
  ```
  This talks to the running app over 127.0.0.1 only, with a new secret every
  launch.
- **Phone:** ⚙ → Remote Control starts the dashboard (local network only)
  and shows a QR code to scan. The phone page has protocol and diagnostics
  buttons.

![Phone](screenshots/mark4-phone-app.png)

---

## 7. Security and privacy

- **Security watch** (on by default): alerts on a new device joining your
  network, a removable drive being plugged in, or a program in Temp or
  Downloads using a lot of CPU for a sustained period.
- **Presence** (off by default): after *"learn my face"*, the webcam briefly
  checks every 15–60 s. JARVIS welcomes you back after 5+ minutes away and
  notices strangers. Only a 128-number face description is stored, never a
  photo; *"forget my face"* deletes it.
- **Guest mode** switches on when presence sees a stranger while you're away,
  or when you say *"lock down"*. Messages, files, browser control, protocols,
  memory, accounts and power actions are refused, and JARVIS won't share
  anything personal. **Only your face unlocks it**, never a voice command; if
  no face is enrolled, unlocking needs an on-screen button.
- **Phone dashboard hardening:** it starts only on demand, opens one LAN-only
  firewall port, rate-limits pairing codes, expires logins, and verifies the
  script it serves.

**Old firewall rules.** Earlier versions (e.g. Mark-LII) may have added broad
rules. Check and remove them in an **admin** PowerShell:
```powershell
Get-NetFirewallRule -DisplayName "JARVIS Dashboard*" | Format-Table DisplayName, Enabled
Remove-NetFirewallRule -DisplayName "JARVIS Dashboard Port 8000","JARVIS Dashboard Port 8001","JARVIS Dashboard Python"
```

---

## 8. Google Calendar and Gmail (optional, read-only)

1. Go to <https://console.cloud.google.com/> and create a project.
2. **APIs & Services → Library:** enable **Google Calendar API** and
   **Gmail API**.
3. **OAuth consent screen:** choose *External*, fill in the app name and your
   email, and add yourself as a **test user**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.**
   Download the JSON.
5. Save it as `config/client_secret.json` in the JARVIS folder.
6. Say *"connect my Google account"* (or System Settings → Accounts →
   Connect) and approve in the browser.

JARVIS asks only for **read-only** access to your calendar and mail. You get
the AGENDA panel, meeting reminders about 10 minutes ahead, and calendar and
mail in the morning briefing. Disconnect any time from System Settings.

---

## 9. Settings

⚙ → **System Settings** holds everything in one place: HUD style, sound
effects, tray behaviour, borderless window, security watch, lock down /
unlock, presence, Google, and remote access.

---

## 10. When things go wrong

| Symptom | What to do |
|---|---|
| HUD says **OFFLINE** | No connection to Gemini. Typed local commands still work (protocols, diagnostics, media, volume, open app, lock). |
| Hotkey does nothing | Another program owns Ctrl+Alt+J; the log shows `[Summon] … unavailable`. |
| No Now Playing | The player doesn't publish to Windows' media controls, or the optional `winrt-*` packages aren't installed. |
| Something crashed | See `logs/crash-*.txt`; the full console log is in `logs/jarvis.log`. |

---

## 11. For developers

```powershell
.\.venv\Scripts\python.exe -m pytest      # ~200 tests, ~15 s
```

Tests never touch your real config, network list, webcam, media player or
Google account. Design notes and measurements are in `JARVIS_PLAN.md`
(Mark I) and `JARVIS_MK2_PLAN.md` (Marks II–VI).
