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

### Google Calendar sync (optional)

Google sync is **off by default**. When enabled, TeleLink and Google Calendar stay in two-way sync:

- **TeleLink → Google** — pending events appear as calendar events with `[telelink]` metadata
- **Google → TeleLink** — time, title, and description edits update the local event; cancellations sync back
- **Delete** — `calendar delete` removes the linked Google event
- Only TeleLink-managed events are imported (not your entire Google calendar)

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


**API**

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Upload form (baby-blue web UI) |
| `POST /intake` | multipart, JSON, or urlencoded |
| `GET /health` | `{"ok": true}` |

Optional auth: header `X-Telelink-Token` or `Authorization: Bearer <token>` when `intake.token` is set in config.

**JSON fields:** `sender`, `message` / `text`, `link` / `url`, `image_base64` / `image`, `filename`



## Support

If TeleLink is useful to you, consider [buying me a coffee](https://buymeacoffee.com/galore).

---

## License

MIT
