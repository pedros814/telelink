> **For AI assistants:** Read **[`AGENTS.md`](AGENTS.md)** first (or run `.\telelink.ps1 agent context`). Do not explore the codebase before running CLI commands. Setup from scratch: [`.skills/telelink/SETUP.md`](.cursor/skills/telelink/SETUP.md). Full skill: [`.cursor/skills/telelink/SKILL.md`](.cursor/skills/telelink/SKILL.md).

# TeleLink

**Your iPhone on Windows — for you and your AI agents.**

TeleLink is a local Windows CLI that bridges **Phone Link** (iPhone paired to your PC) with your terminal, scripts, and coding assistants like **Cursor** and **Claude Code**. It watches incoming messages, sends SMS on your behalf, **schedules messages for later**, moves files between phone and PC, and keeps structured data on disk so agents can read notifications and act without a cloud service.

No Mac. No paid APIs. Everything stays on your machine.

---

## What TeleLink does

| Capability | What it means |
|------------|----------------|
| **Watch & capture** | Live notification watcher → structured log (`caught.jsonl`), attachments, contact tags |
| **Send SMS** | `send` opens Phone Link compose; optional UI automation taps Send for agents |
| **Intake** | Phone → PC over Wi‑Fi: web form, API, or **iOS Shortcut** pushes text, links, and images |
| **Outtake** | PC → phone: upload files to GitHub and show a **QR code** or SMS link |
| **Contacts** | Match senders to people; route, filter, and resolve names for `send` |
| **Calendar** | Schedule SMS for later; optional Google Calendar two-way sync |
| **Call log** | Phone Link call toasts → `calls.jsonl`; `calls` / `missed` commands and reminders |
| **Agent-ready** | Short-lived vision snapshots (`.analyze/`), owner tone, `@` shortcuts in messages |

```
                    ┌─────────────────────────────────────────┐
  iPhone ──────────►│  Phone Link (Windows)                   │
                    │    toasts · SMS compose · photo folders │
                    └──────────────┬──────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
    watcher                   send / sync                 harvest
  (notifications)          (SMS via Phone Link)      (DB + folder images)
         │                         │                         │
         └────────────┬────────────┴─────────────────────────┘
                      ▼
            data/caught.jsonl · contacts.jsonl · calls.jsonl · attachments/
                      │
                      └──► data/.analyze/  (AI snapshot — Cursor / Claude)

  iPhone ── Wi‑Fi ──► intake :8787  ──► same caught + attachments pipeline
  PC files ─────────► outtake (GitHub QR/SMS)

  calendar ─────────► scheduled SMS (SQLite) ──► fires via send / Phone Link
                      └── optional ↔ Google Calendar (two-way sync)

  Phone Link calls ─► watcher ──► data/calls.jsonl  (missed / incoming / outgoing)
```

---

## Built for Cursor, Claude Code, and the terminal

TeleLink is designed so an agent on your PC can **see** what your phone received and **respond** without copy-pasting from Phone Link.

**Read what arrived**

- `caught` — browse notifications as a table, JSON, or filtered views
- `data/.analyze/latest.json` + `latest.png` — small centered preview of the last attachment (vision-friendly; auto-expires)
- `data/caught.jsonl` — full structured history

**Send on your behalf**

```text
send "Client Name" Running about 10 minutes late, thanks for waiting
send +15551234567 On my way
send in%2hour% girlfriend Hey bro this is an example message
```

`send in%<when>%` schedules via the calendar (does **not** send immediately). `send <who> <msg>` still sends now. Case-insensitive (`IN%2HOUR%`). Optional `%` around the contact: `send in%30m% %girlfriend% On my way`.

- Resolves names from `data/contacts.jsonl`
- `messaging.method: auto` uses UI automation to click **Send** in Phone Link (best-effort; see limits below)
- Set `owner.talking_tone` in config so agents draft SMS in your voice

**Schedule for later**

```text
calendar add love-note girlfriend "2pm today" "I love you! See you tonight."
calendar add follow-up "Client" "in 3h" "Just sent the files — let me know."
```

- Events live in SQLite and fire automatically while TeleLink is running (shell or watcher)
- Optional **Google Calendar** two-way sync — edit in either place, both stay aligned

**Share files both ways**

- **Intake** — iPhone uploads to your PC (Shortcut, browser, or `curl`)
- **Outtake** — PC uploads to GitHub; phone scans QR or opens SMS link

Install the project skill for agents: `.cursor/skills/telelink/` (copy to `~/.cursor/skills/telelink/` for all projects). Run `how` or `help <topic>` inside TeleLink for the full in-terminal guide.

---

## Quick start

### 1. Pair Phone Link

Pair your iPhone with **Phone Link** / Link to Windows. Enable **messages** and **photo sync**.

### 2. Install

```powershell
cd path\to\Telelink CLI
.\scripts\setup.ps1
```

Edit `config.yaml` (created from `config.example.yaml`). Set **owner** fields and add contacts in `data/contacts.jsonl` (see `assets/contacts.example.jsonl`) or via `contacts add`.

### 3. Notification access

```powershell
start ms-settings:privacy-notifications
```

Allow **Python** or **Windows Terminal** for the account that runs TeleLink.

### 4. Run

Double-click **`start.bat`** (runs as admin) or:

```powershell
.\.venv\Scripts\Activate.ps1
python -m telelink              # interactive shell
python -m telelink watcher      # capture window (keep open while listening)
python -m telelink caught       # browse what was caught
python -m telelink how          # full how-to inside the shell
```

**Daily pattern:** `watcher` in one window → work in the TeleLink shell → `caught` / `calls` / `missed` / `send` / `calendar` / `intake` / `outtake` as needed → `watcher stop` when done. Keep the shell open if you have scheduled events — the calendar scheduler runs in the background.

---

## Commands

| Command | Description |
|---------|-------------|
| `watcher` | Start notification + folder watchers (new console window) |
| `watcher stop` | Force stop the watcher window |
| `listen` / `listen stop` | Aliases for `watcher` / `watcher stop` |
| `caught` | Notifications viewer (table / json / gron) |
| `caught --json` / `--raw` / `--gron` | JSON table, raw lines, gron format |
| `caught --contacts-only` | Only matched-contact notifications |
| `caught --group channel` | Group by platform (iMessage, Instagram, …) |
| `caught last 5` | Recent rows (shell syntax) |
| `contacts` | List contacts and match rules |
| `contacts add Name +1…` | Add or update a contact |
| `contacts --sync-caught` | Import senders from caught log |
| `send <who> <msg>` | SMS via Phone Link (quote names with spaces) |
| `calendar` | Table of pending scheduled SMS events |
| `calendar add <name> <who> <when> <msg>` | Schedule a message (`2pm today`, `in 3h`, `tomorrow 9am`, …) |
| `calendar delay <name> <when>` | Postpone a pending event |
| `calendar delete <name>` | Remove a scheduled event |
| `calendar cancel <name>` | Cancel (keeps row, marks cancelled) |
| `calendar <name> status` | One event — fires at, countdown, errors |
| `calendar status` | Calendar health + Google sync state |
| `calendar connect google` | OAuth to Google Calendar (optional) |
| `calendar sync` | Force two-way Google Calendar sync |
| `calls` | Recent Phone Link calls (default **1d** retention) |
| `calls --limit 20` / `calls 20` | Limit rows (shell or CLI) |
| `missed` | Missed calls only — who called and when |
| `missed --limit 10` / `missed 10` | Limit missed rows |
| `sync` | Re-sync config + jsonl + sqlite + Phone Link DB |
| `sync --caught` | Also import caught senders into contacts |
| `config` | Status dashboard (paths, intake URL, harvest) |
| `config edit <key> <value>` | Set `config.yaml` (auto-save) |
| `config get <key>` / `config list` | Read settings |
| `doctor` | Alias for `config` |
| `intake` | LAN upload server — menu: QR or SMS link |
| `intake --qr` / `--sms` / `--wait` | Skip menu; `--wait` until Ctrl+C |
| `intake global` | Public URL via cloudflared/ngrok |
| `intake stop` | Stop server + tunnel |
| `outtake <url\|file…>` | QR/SMS share; multiple files → zip → GitHub |
| `how` | Full terminal how-to guide |
| `help <topic>` | e.g. `help intake`, `help calendar`, `help calls`, `help analyze` |
| `wipe calls` | Clear `data/calls.jsonl` |
| `status` | Quick caught summary |

Shell keys: `ctrl+h` help · `ctrl+b` back · `ctrl+c` cancel · `clear` / `cc` clears screen.

---

## Watcher — receive and watch notifications

The **watcher** is a separate console window that must stay open while you want live capture.

- **Toasts** — WinRT notification listener (PowerShell fallback); **call toasts** (missed, incoming, outgoing) go to `data/calls.jsonl`, not `caught`
- **Images** — watches Phone Link photo folders; optional **harvest** polls Phone Link SQLite for blobs Phone Link never synced
- **Contacts** — tags each row when `match` rules hit in `data/contacts.jsonl`
- **Preview** — inline image preview in the watcher window (configurable)
- **Analyze** — writes `data/.analyze/latest.png` + `latest.json` for each new attachment (short TTL)

```powershell
python -m telelink watcher
python -m telelink watcher --foreground   # same terminal, no new window
python -m telelink caught
python -m telelink caught contacts
python -m telelink caught --json
```

`routing.only_contacts: true` skips notifications that do not match any managed contact.

---

## Send — SMS from the terminal (and from agents)

```text
send "Shawk" Running 10 min late
send +15551234567 Hello from TeleLink
```

**How it works**

1. Resolves `<who>` against `data/contacts.jsonl` (name or phone)
2. Expands **@ shortcuts** in the message body from `owner` in config (see below)
3. Opens Phone Link SMS compose with the number and text filled
4. With `messaging.method: auto`, UI automation (`pywinauto`) clicks **Send** — best effort; verify on the phone

**Limits (iPhone + Phone Link)**  
Microsoft does not expose a silent send API. Apple may still require confirmation on the iPhone. TeleLink automates what Phone Link allows; it cannot bypass carrier or Apple restrictions. See `assets/messaging-help.txt`.

```yaml
messaging:
  method: auto          # manual | auto | adb (Android USB only)
  auto_timeout_seconds: 12
```

### Send shortcuts (@tags)

Use these in the message body; TeleLink expands them before compose opens:

| Tag | Expands to |
|-----|----------------|
| `@nameshort` | `owner.personal_name_short` |
| `@namefull` | `owner.personal_name_full` |
| `@business` | `owner.business_name` |
| `@email` | `owner.work_email` |
| `@timezone` | `owner.timezone` |
| `@tone` | `owner.talking_tone` (full string — usually for agents, not literal SMS) |

Also: `/n` = newline in the message body.

**For AI agents:** read `owner.talking_tone` and draft the SMS in that voice. Use `@nameshort` / `@business` in the body; do not paste `@tone` unless you want the tone text inside the message.

```text
config edit tone Professional, direct, human tone. No em dashes.
send "Client" Hi @nameshort here — running about 10 minutes late
```

---

## Calendar — scheduled SMS and Google Calendar sync

Schedule text messages to send later. TeleLink stores events in SQLite, fires them through the same **send** / Phone Link path when due, and can optionally keep everything in sync with **Google Calendar**.

### How scheduled events work

1. You (or an agent) run `calendar add` with a short **name**, **who** (contact or `+number`), **when**, and **message**
2. The event is saved as `pending` in `data/telelink.db` (`calendar_events` table)
3. While TeleLink is running, a background scheduler checks every **30 seconds** (configurable)
4. When `fire_at` is reached, TeleLink calls `send` — same compose / auto-send behavior as immediate SMS
5. Status becomes `completed` or `failed` (never returned to `pending`; stuck in-flight rows are marked failed without retry)

**Important:** the interactive shell or watcher session must stay open for events to fire. A one-shot `python -m telelink calendar add …` without a running shell will not send at the scheduled time.

Every **15 minutes**, if any events are still pending, the shell prints a reminder (same style as the intake server uptime label):

```text
CALENDAR  2 scheduled events waiting to fire
  View: calendar  · cancel: calendar delete <name>
```

### Commands

```text
calendar                                              # table of pending events
calendar add love-note girlfriend "in 3h" "I love you!"
calendar add dinner "Mom" "2pm today" "Running 10 min late"
calendar delay love-note 1h                           # postpone
calendar delete love-note                             # remove
calendar love-note status                             # one event detail
calendar status                                       # scheduler + Google health
```

### Time expressions

All times use `owner.timezone` from `config.yaml` (e.g. `America/Denver`).

| Style | Examples |
|-------|----------|
| Relative | `in 3h`, `in 45m`, `in 1d` |
| Clock + day | `2pm today`, `today 2pm`, `tomorrow 9am`, `9:30 am tomorrow` |
| Delay shorthand | `30m`, `2h` (for `calendar delay`) |
| ISO | `2026-05-28T14:00` |

### For AI agents

When a user asks to send a message at a specific time:

1. Read `owner.talking_tone` and draft the SMS in that voice
2. Resolve the contact from `data/contacts.jsonl`
3. Schedule with a short slug name:

```text
calendar add love-2pm girlfriend "2pm today" "I love you baby! …funny quote…"
```

Check `calendar` or `calendar <name> status` to confirm. Do not use `@tone` in the body unless the user wants the full tone string in the SMS.

### Google Calendar sync (optional)

Google sync is **off by default**. When enabled, TeleLink and Google Calendar stay in two-way sync:

- **TeleLink → Google** — pending events appear as calendar events with `[telelink]` metadata
- **Google → TeleLink** — time, title, and description edits update the local event; cancellations sync back
- **Delete** — `calendar delete` removes the linked Google event
- Only TeleLink-managed events are imported (not your entire Google calendar)

**1. Install optional Python packages**

```powershell
pip install google-api-python-client google-auth-oauthlib
```

**2. Google Cloud Console**

- Create a project → enable **Google Calendar API**
- Create **OAuth 2.0 Client ID** (Desktop app)
- Download the JSON credentials file

**3. Configure TeleLink**

```yaml
calendar:
  enabled: true
  poll_seconds: 30
  remind_interval: 15m
  google:
    enabled: true
    credentials_file: path/to/oauth-client.json
    calendar_id: primary
    sync_interval: 5m
```

Or via CLI:

```text
config edit google_calendar true
config edit google_credentials C:\path\to\oauth-client.json
```

**4. Authorize and sync**

```text
calendar connect google    # browser OAuth; token saved under data/
calendar sync              # force pull + push
calendar status            # shows Google connection + last sync
```

Background sync runs every `calendar.google.sync_interval` (default **5m**) while TeleLink is running.

**Without Google:** local scheduling works fully on its own — no Google account or API keys required.

See `how calendar` or `help calendar` (in the shell) for the full topic guide.

---

## Calls — Phone Link call log

TeleLink captures **Phone Link call toasts** (missed, incoming, outgoing) into a separate log. Call rows are **not** duplicated into `caught` — use `calls` and `missed` for call history.

### Requirements

**Import from Phone Link (recommended):** run `sync` or `calls sync` to pull call history from `calling.db` on disk — the same store the Phone Link **Calls** tab uses. This works even if the watcher was not running.

**Live toasts (optional):** the watcher can also capture call notifications as they appear. Keep the watcher open for real-time capture between syncs.

### Commands

```text
sync                     # contacts + import calls from Phone Link calling.db
calls sync               # import calls only
calls                    # all recent calls (within TTL)
calls 20                 # last 20 rows (shell syntax)
calls --limit 20           # same via CLI flag
missed                   # missed calls only
missed 10
```

If Phone Link shows missed calls but `missed` is empty, your missed calls may be older than `calls.ttl` (default **1d**). Try `config edit calls_ttl 7d` then `calls sync`.

The table shows contact match (when `match` rules hit), caller name/number, kind (`missed` / `incoming` / `outgoing`), time, and toast detail.

### Retention

Entries older than **`calls.ttl`** (default **`1d`**) are pruned at startup, in the watcher, and every **5 minutes**.

```yaml
calls:
  enabled: true
  file: calls.jsonl
  ttl: 1d
  remind_interval: 10m
```

```text
config edit calls_ttl 2d
config edit calls_enabled false
config edit calls_remind 15m
```

### Reminders

While the interactive shell is running:

- **Intake uptime line** — when `intake` is live and missed calls exist, the periodic reminder includes the count, e.g. `still running · up 12m · 2 missed calls`
- **CALLS label** — every **`calls.remind_interval`** (default **`10m`**), prints a missed-call reminder when intake is running **or** any missed calls are in the log:

```text
CALLS  2 missed calls
  View: missed · all calls: calls
```

Clear the log with `wipe calls`. See `how calls` or `help calls` in the shell.

---

## Intake — phone → PC (Wi‑Fi upload)

When Phone Link does not sync photos or you want to push content from the phone without waiting for a toast:

1. On PC: `intake` → choose **QR** or **SMS** with `http://<LAN-IP>:8787/`
2. iPhone on the **same Wi‑Fi**; allow Python on Windows Firewall (Private)
3. Browser form or API: sender, message, link, file → saved to **caught** + **attachments**

```powershell
python -m telelink intake
python -m telelink intake --qr
python -m telelink intake global    # public URL (cloudflared/ngrok)
python -m telelink intake stop
```

**API**

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Upload form (baby-blue web UI) |
| `POST /intake` | multipart, JSON, or urlencoded |
| `GET /health` | `{"ok": true}` |

Optional auth: header `X-Telelink-Token` or `Authorization: Bearer <token>` when `intake.token` is set in config.

**JSON fields:** `sender`, `message` / `text`, `link` / `url`, `image_base64` / `image`, `filename`

### iOS Shortcut (recommended)

Full step-by-step: **`assets/iphone-intake.txt`**

Summary — create a Shortcut that **POST**s to `http://YOUR-PC-IP:8787/intake`:

1. **Receive** Images and Text from Share Sheet
2. **Get Text** / **Get Images** from Shortcut Input
3. **Get Contents of URL** — Method POST, Form fields: `sender`, `message`, `image`
4. Name it e.g. **Send to TeleLink**

In iMessage: tap image → **Share** → **Send to TeleLink**.

Automated folder polling variant: **`assets/ios-auto-intake.txt`**.

---

## Outtake — PC → phone (QR or SMS link)

Share a URL or upload file(s) from your PC; TeleLink uploads to **GitHub** and prints a **QR code** or SMS-friendly link for your phone.

```powershell
python -m telelink outtake https://example.com/doc
python -m telelink outtake C:\path\to\report.pdf
python -m telelink outtake report.pdf diagram.png   # multiple → zip → one URL
```

**Setup**

```yaml
outtake:
  github:
    token: ""    # or set GITHUB_TOKEN env
    repo: telelink-sharing
```

Files auto-delete from the repo after `outtake.auto_delete` (default 30m). Confirm before upload in the interactive flow.

---

## AI agents — `.analyze` folder

When `analyze.screenshot: true` (default), each caught **image or video** writes a short-lived snapshot agents can read without opening huge attachments:

| File | Use |
|------|-----|
| `data/.analyze/latest.json` | Read **first** — sender, channel, message kind, task id, timestamp |
| `data/.analyze/latest.png` | Read **second** — centered ~700×500 preview |

Files auto-delete after `analyze.ttl` (default **4 minutes**). Disable with `config edit analyze_screenshot false`.

```powershell
config get analyze.screenshot
help analyze
```

**Workflow for Cursor / Claude Code**

1. User runs `watcher`; phone receives a message with an image
2. Agent reads `latest.json` then `latest.png`
3. Agent drafts reply: `send "Contact" …` following `owner.talking_tone`
4. Optional: `outtake` to return a file, or `intake` guide if user needs to push from phone
5. Optional: `calendar add` when the user wants a message sent at a specific time

---

## Data layout

| File | Purpose |
|------|---------|
| `data/caught.jsonl` | One JSON object per caught notification |
| `data/calls.jsonl` | Phone Link call log (missed / incoming / outgoing) |
| `data/contacts.jsonl` | Contacts + `match` patterns |
| `data/telelink.db` | SQLite — contacts, calendar events, KV |
| `data/localstorage.json` | Runtime prefs and sync timestamps |
| `data/attachments/` | Copied images and screenshots (full resolution) |
| `data/.analyze/latest.png` | AI snapshot — centered preview when analyze is on |
| `data/.analyze/latest.json` | Metadata for latest snapshot |
| `data/sent.jsonl` | Outbound SMS log (when `messaging.log_sent` is on) |
| `data/.calendar-google-token.json` | Google OAuth token (optional; when Calendar sync is on) |

Scheduled SMS events are stored in the **`calendar_events`** table inside `telelink.db` (not a separate file). Clear with `wipe calendar` or `wipe db`.

Set `output.auto_delete_caught` in `config.yaml` to expire old caught rows (e.g. `"30m"`, `"1h"`). Default is `false` — messages never expire.

---

## Contacts

Managed contacts live in **`data/contacts.jsonl`**, not in `config.yaml`:

```json
{"name": "Client", "phone": "+15551234567", "match": ["client", "5551234567"], "platform": "imessage", "managed": true}
```

- `managed: true` — notifications can be tagged with this contact
- `managed: false` — personal (e.g. yourself); `send` only, no notification matching

**Owner** (you) is configured under `owner:` in `config.yaml` — not as a contact row.

```powershell
python -m telelink contacts
python -m telelink contacts add "Client" +15551234567
python -m telelink sync --caught
```

**Phone Link address book:** On startup/sync, TeleLink discovers `contacts.db` inside the Phone Link app package (read-only snapshot — it never writes to Phone Link files). If you have multiple paired-device folders, it picks the database with the most contacts and recent sync time, then remembers that path in `data/localstorage.json`. Override only if needed: `phone_link.contacts_db` in `config.yaml`. Run `python -m telelink config` to see which file is in use.

---

## Config highlights

| Area | Keys | Notes |
|------|------|-------|
| Owner | `owner.business_name`, `personal_name_short`, `talking_tone`, … | @tags in `send`; tone for agents |
| Routing | `routing.only_contacts`, `ignore_channels` | Filter toasts |
| Intake | `intake.port` (8787), `intake.token` | LAN server; optional auth |
| Outtake | `outtake.github.token`, `repo` | Or `GITHUB_TOKEN` env |
| Messaging | `messaging.method`, `auto_timeout_seconds` | manual / auto / adb |
| Calendar | `calendar.enabled`, `poll_seconds`, `remind_interval` | Scheduled SMS; 15m pending reminder |
| Calls | `calls.enabled`, `calls.ttl` (1d), `calls.remind_interval` (10m) | Call log in `data/calls.jsonl`; missed-call reminders |
| Google Cal | `calendar.google.enabled`, `credentials_file`, `calendar_id` | Optional two-way sync |
| Analyze | `analyze.screenshot`, `analyze.ttl` | Agent vision snapshots |
| Harvest | `harvest.enabled`, `poll_seconds` | Phone Link DB scrape |

```text
config edit business YourCo
config edit tone Professional, direct, human tone.
config edit port 9000
config edit github_token ghp_...
config edit google_calendar true
config edit google_credentials C:\path\to\oauth-client.json
```

---

## Optional extras

| Feature | How |
|---------|-----|
| **OCR** | `winget install UB-Mannheim.TesseractOCR` then `ocr.enabled: true` |
| **Auto-send SMS** | `messaging.method: auto` + `pip install pywinauto` — see `assets/messaging-help.txt` |
| **Intake guides** | `assets/iphone-intake.txt`, `assets/ios-auto-intake.txt` |
| **Command cheat sheet** | `assets/help.txt` |
| **Agent skill** | `.cursor/skills/telelink/SKILL.md` + `reference.md` |
| **Scheduled SMS** | `calendar add` — keep shell open for fire-offs |
| **Call log** | `watcher` + `calls` / `missed` — `help calls` |
| **Google Calendar** | `pip install google-api-python-client google-auth-oauthlib` → `calendar connect google` |

---

## Requirements

- **Windows 10/11** with **Phone Link** paired to iPhone
- **Python 3.10+** (venv via `scripts/setup.ps1`)
- Same Wi‑Fi for **intake** (phone and PC)
- **GitHub token** for **outtake** file uploads (or use URL-only outtake)
- **Google OAuth client JSON** + API packages only if you enable **Google Calendar** sync (`calendar.google.enabled`)

---

## Support

If TeleLink is useful to you, consider [buying me a coffee](https://buymeacoffee.com/galore).

---

## License

MIT
