# TeleLink reference

Detailed reference for agents. Main workflow: [SKILL.md](SKILL.md). **Setup from scratch:** step-by-step install and user Q&A are in [SETUP.md](SETUP.md).

## Requirements

- **OS:** Windows 10/11
- **Phone:** iPhone paired with **Phone Link** (Link to Windows)
- **Python:** 3.10+ (venv via `scripts/setup.ps1`)
- **Optional:** Tesseract OCR, `pywinauto`, `pymobiledevice3`, `cloudflared`/`ngrok`

## Install

For a full guided setup (phases, minimal user questions, tokens, verification), use **[SETUP.md](SETUP.md)**.

```powershell
.\scripts\setup.ps1
# Edit config.yaml, data/contacts.jsonl
start ms-settings:privacy-notifications
python -m telelink
```

Batch files: `start.bat` (admin shell), `watcher.bat`, `listen.bat`, `telelink.ps1`.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  python -m telelink  (console.py → statey interactive)      │
│    cli.py subcommands │  TeleLinkService (service.py)       │
└───────────────────────────────┬─────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  notifications_*          folder watch            harvest loop
  (WinRT / PS)             (watchdog)              (Phone Link DB)
        │                       │                       │
        └───────────────────────┴───────────────────────┘
                                ▼
                    store.py / db.py / caught.jsonl
                                ▼
                    contacts.py match → contact tag
```

**Intake path:** `IntakeServer` → `POST /intake` → `ingest_upload()` → same store.

**Outtake path:** `outtake_share` → GitHub API or git push → QR via `qr_terminal.py`.

## All CLI commands

### `watcher` / `listen`

```text
watcher                    # new console window
watcher --foreground       # run in current terminal
watcher stop               # kill watcher window
```

Watcher runs `TeleLinkService` with notification listener, media debounce, optional harvest/iPhone pull. **Call toasts** (missed/incoming/outgoing) append to `data/calls.jsonl` — not `caught`. Intake is separate (`intake` command); uploads still appear in the watcher window via caught.jsonl tail.

### `caught`

```text
caught
caught --json              # all JSON keys as columns
caught --raw               # raw JSONL lines
caught --gron              # gron format
caught --limit 20
caught --channel imessage
caught --contact "Name"
caught --sender substring
caught --kind image
caught --contacts-only
caught --group channel     # platform | contact | sender | kind | client
```

Shell shortcuts (interactive): `caught contacts`, `caught last 5`, `caught json`, `caught group channel`.

### `contacts`

```text
contacts
contacts -q search
contacts --add "Name" --phone +1… --match pat1,pat2 --platform imessage
contacts --add "Me" --phone +1… --personal
contacts --remove Name
contacts --sync-config       # legacy config import
contacts --sync-caught       # phone-like senders from caught
```

### `send`

```text
send <to> <message words…>
```

`to` = contact name, alias, or `+phone`. Message supports owner `@tags` and `/n` newlines.

| @tag | `owner` key |
|------|-------------|
| `@nameshort`, `@short` | `personal_name_short` |
| `@namefull`, `@full` | `personal_name_full` |
| `@business` | `business_name` |
| `@email` | `work_email` |
| `@timezone` | `timezone` |
| `@tone`, `@talkingtone`, `@talking_tone` | `talking_tone` |

Agents drafting SMS: apply `owner.talking_tone` to the message text; avoid `@tone` in the body unless the full tone string should appear in the SMS.

`messaging.method` values: `auto`, `phone_link_auto`, manual paths, `adb` (Android USB).

Log: `data/sent.jsonl` when `messaging.log_sent: true`. By default only the **5 newest** lines are kept (`messaging.sent_log_max_entries`); set `off` / `false` / `0` for unlimited.

### `calendar`

Schedule SMS to send later. Stored in SQLite `calendar_events`. Fires while TeleLink shell or watcher is running.

```text
calendar
calendar add <name> <who> <when> <message…>
calendar delay <name> <when>
calendar delete <name>
calendar cancel <name>
calendar <name> status
calendar status
calendar connect google    # optional OAuth
calendar sync              # optional Google two-way sync
```

**When expressions:** `in 3h`, `30m`, `2pm today`, `tomorrow 9am`, ISO `2026-05-28T14:00` (uses `owner.timezone`).

**Shell reminder:** Every `calendar.remind_interval` (default `15m`), prints pending event count if > 0 (like intake server reminders).

### `calls` / `missed`

Phone Link call toasts (missed, incoming, outgoing) are captured by the **watcher** into `data/calls.jsonl`. They are **not** duplicated into `caught`.

```text
calls
calls --limit 20
missed
missed --limit 10
```

**Retention:** `calls.ttl` (default `1d`) — entries older than TTL are pruned at startup, in the watcher, and every 5 minutes.

**Reminders:**

- Intake uptime line includes missed count when > 0: `still running · up 12m · 2 missed calls`
- Every `calls.remind_interval` (default `10m`), shell prints `CALLS` with missed count when intake is running or missed count > 0:

```text
CALLS  2 missed calls
  View: missed · all calls: calls
```

**Shell limits:** `calls 20`, `missed 10` (positional digits in interactive shell).

**Config:**

```yaml
calls:
  enabled: true
  file: calls.jsonl
  ttl: 1d
  remind_interval: 10m
```

**Aliases:** `config edit calls_ttl 2d` · `calls_enabled` · `calls_remind`

**Wipe:** `wipe calls`

**Google Calendar (optional):**

```yaml
calendar:
  google:
    enabled: true
    credentials_file: path/to/oauth-client.json
    calendar_id: primary
```

```text
pip install google-api-python-client google-auth-oauthlib
config edit google_calendar true
calendar connect google
calendar sync
```

Edits in Google Calendar or TeleLink stay in sync via `google_event_id` and `[telelink]` metadata in event descriptions.

**Agents:** Draft message with `owner.talking_tone`, then `calendar add` with slug name, contact, when, body.

### `sync`

```text
sync
sync --caught              # import caught senders as contact suggestions
```

Sources: config, jsonl, sqlite, localStorage, Phone Link SQLite (`sync.import_phone_link_db`).

### `config` / `doctor`

```text
config                     # status dashboard
config list
config get intake.port
config edit business Acme
config edit intake.token mysecret
config edit routing.only_contacts true
```

### `intake`

```text
intake                     # menu: 1 QR, 2 SMS
intake --qr
intake --sms
intake --wait              # block until Ctrl+C
intake global              # public tunnel
intake global --qr --wait
intake stop
```

**LAN URL:** `http://<LAN-IP>:<port>/` (default port 8787)  
**POST endpoint:** `/intake`  
**PID file:** `data/intake.pid`

`intake.enabled: false` disables the `intake` command only; watcher never starts the server.

### `outtake`

```text
outtake https://youtube.com/watch?v=…
outtake C:\path\file.pdf
outtake a.pdf b.png          # zip then upload
outtake --qr / --sms
```

Config `outtake.prefer`: `auto` | git clone in `data/outtake-repo` | GitHub API.

### Other

```text
how                        # full guide
how intake                 # topic sections
status                     # quick summary
shell                      # explicit interactive mode
--version
```

## config.yaml sections

### `owner`

Business/personal identity for tagging and `send` expansion — **not** a contact.

| Key | Example | Notes |
|-----|---------|-------|
| `business_name` | Your Business | `@business` |
| `personal_name_short` | Alex | `@nameshort` |
| `personal_name_full` | Your Name | `@namefull` |
| `work_email` | you@example.com | `@email` |
| `timezone` | America/Denver | `@timezone` |
| `talking_tone` | multiline string | `@tone` — voice guide for drafts; `config edit tone …` |

### `routing`

| Key | Default | Meaning |
|-----|---------|---------|
| `unmatched_label` | `unassigned` | Label when no contact match |
| `only_contacts` | `false` | Drop unmatched notifications |
| `ignore_channels` | `[]` | Skip platforms |

### `phone_link`

`app_names`, `app_user_model_ids` — notification filter.  
`watch_folders` — image drop paths.  
`auto_discover_folders` — scan for Phone Link package paths.

### `media`

`correlate_window_seconds`, `organize_by_sender`, `debounce_seconds` — tie images to notifications.

**`media.preview`** (watcher terminal display — **Pillow**, no extra install):

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `true` | Inline preview in watcher window |
| `width` | `58%` | Terminal width % or column count |
| `height` | — | Optional row cap (omit for aspect ratio) |
| `max_edge` | `960` | Downscale huge images before render |

Uses 24-bit half-block characters (works in Windows Terminal and modern conhost).

### `analyze` (AI snapshot folder)

Short-lived centered PNG for Cursor/Claude — **not** the full attachment copy.

| Key | Default | Meaning |
|-----|---------|---------|
| `screenshot` | `true` | Master switch (`false` disables) |
| `ttl` | `4m` | Auto-delete files in `.analyze/` after this (`off` = no prune) |
| `width` | `700` | Canvas width (px) |
| `height` | `500` | Canvas height (px) |
| `margin` | `24` | Padding around centered media |
| `dir` | `.analyze` | Subfolder under `output.dir` |

**Runtime paths** (when enabled):

| Path | Contents |
|------|----------|
| `data/.analyze/latest.png` | Centered preview — **read for vision** |
| `data/.analyze/latest.json` | `sender`, `channel`, `task_id`, `source_file`, `at`, `ttl_seconds` |

**Agent workflow:**

1. `config get analyze.screenshot` or `config` dashboard — confirm not `off`.
2. Read `latest.json` for context, then `latest.png`.
3. Do not routinely read `data/attachments/` (large originals).
4. If files missing: disabled, TTL expired, or no attachment caught yet.

Aliases: `config edit analyze_screenshot false`, `config edit analyze_ttl 10m`.

Module: `telelink/analyze_snapshot.py` · Help: `help analyze`.

### `output`

| Key | Default |
|-----|---------|
| `dir` | `./data` |
| `caught_file` | `caught.jsonl` |
| `auto_delete_caught` | `false` or duration `"30m"`, `"1h"` |
| `contacts_file` | `contacts.jsonl` |
| `sqlite_file` | `telelink.db` |
| `attachments_dir` | `attachments` |

### `sync`

`on_startup`, `import_phone_link_db`, `import_caught_on_startup`.

### `messaging`

| Key | Notes |
|-----|-------|
| `enabled` | Master switch |
| `method` | `auto` uses `messaging_auto.py` |
| `auto_timeout_seconds` | UI wait |
| `auto_delay_ms` | Delay before clicking Send |
| `auto_verify_before_unfocus` | Poll compose/thread before Ctrl+N / minimize |
| `auto_verify_timeout_ms` | Max wait per verify pass (default 8000) |
| `auto_verify_poll_ms` | UI poll interval (default 400) |
| `auto_verify_retry_send` | Tap Send again if compose still has text |
| `auto_sent_requires_verify` | `auto_sent` false unless verify passes |
| `sent_log` | Relative to output dir |
| `sent_log_max_entries` | `5` — keep newest N lines; `off` / `false` / `0` = unlimited |

### `intake`

| Key | Default | Notes |
|-----|---------|-------|
| `enabled` | `true` | Allow `intake` command (not tied to watcher) |
| `host` | `0.0.0.0` | Bind all interfaces |
| `port` | `8787` | |
| `token` | `""` | `X-Telelink-Token` / Bearer |
| `global_tunnel` | `auto` | `cloudflared` \| `ngrok` |
| `global_server` | `pyhttpd` | `pyhttpd` \| stdlib |
| `public_url` | `""` | Manual override |

### `outtake.github`

`token`, `owner`, `repo` (default `telelink-sharing`), `branch`, `path_prefix`.

### `harvest` / `listener` / `ocr` / `parser`

- **harvest:** background Phone Link DB + cache scraping
- **listener:** notification poll interval
- **ocr:** Tesseract on images (`winget install UB-Mannheim.TesseractOCR`)
- **parser:** `urgent_words` (high priority), `muted_words` (skip watcher/caught). Channel muting: `routing.ignore_channels` (e.g. `instagram`)

### `calls`

Phone Link call toasts → `data/calls.jsonl`. Requires **watcher** running when the toast appears.

| Key | Default | Notes |
|-----|---------|-------|
| `enabled` | `true` | Set `false` to disable capture |
| `file` | `calls.jsonl` | Relative to `output.dir` |
| `ttl` | `1d` | Auto-delete older entries (`ttl_seconds` computed at load) |
| `remind_interval` | `10m` | Shell missed-call reminder interval |

**Config edit aliases:** `calls_enabled`, `calls_ttl`, `calls_remind`

**Wipe:** `wipe calls`

### `iphone_pull` (optional, not in example)

```yaml
iphone_pull:
  enabled: false
  poll_seconds: 60
```

Requires `pymobiledevice3`, trusted USB device.

## Intake HTTP API

### `GET /`

HTML upload form.

### `POST /intake`

**Multipart fields:** `sender`, `message`, `link`, `file` (first file wins).

**JSON:**

```json
{
  "sender": "+15551234567",
  "message": "note text",
  "link": "https://…",
  "image_base64": "<base64>",
  "filename": "shot.png"
}
```

**Response:** HTML success page if `Accept: text/html`, else `{"ok": true, "saved": true}`.

**Errors:** 401 unauthorized, 400 bad body, 500 with themed HTML if HTML accept.

### `GET /help`

JSON schema hint for Shortcut builders.

### `GET /health`

`{"ok": true}`

## caught.jsonl fields (typical)

Varies by source; common keys include notification text, sender, platform/channel, timestamps, attachment paths, matched `contact`, classification flags. Use `caught --json` to see all keys present in your log.

## calls.jsonl fields (typical)

One JSON object per Phone Link call toast. Common keys: `kind` (`missed` | `incoming` | `outgoing`), `caller`, `sender_id`, `body`, `timestamp`, `contact` (when matched). Not written to `caught.jsonl`.

## Optional features

| Feature | Enable | Notes |
|---------|--------|-------|
| AI analyze snapshot | `analyze.screenshot: true` (default) | `data/.analyze/latest.png` |
| Call log | `calls.enabled: true` (default) | `data/calls.jsonl`; watcher required |
| Watcher photo preview | `media.preview.enabled` (default on) | Pillow in `requirements.txt` |
| OCR | `ocr.enabled: true` | Tesseract on disk |
| Auto-send SMS | `messaging.method: auto` | `pywinauto`, fragile |
| iPhone USB pull | `iphone_pull.enabled` | `pymobiledevice3` |
| Intake global | `intake global` | Install cloudflared or ngrok |
| ADB SMS | `messaging` adb path | Android only, not iPhone |

## Project layout

```text
telelink/           # Python package
  cli.py            # Entry + argparse
  console.py        # Interactive shell
  service.py        # Watcher core
  analyze_snapshot.py  # data/.analyze/ for AI
  call_log.py calls.py calls_remind.py  # Phone Link call log
  preview_media.py     # Shared image load / sizing
  terminal_image.py    # Watcher Pillow preview
  intake*.py        # Intake server
  web_theme.py      # Intake HTML/CSS
  chalk.py ink_ui.py  # Terminal theme
  how_guide.py      # how command content
assets/             # banner, help.txt, intake guides
data/               # Runtime output (gitignored)
config.yaml         # Local config (gitignored)
scripts/setup.ps1
```

## Dependencies (requirements.txt)

Core: `watchdog`, `PyYAML`, `ruamel.yaml`, `Pillow`, `qrcode`, WinRT notification packages.

Optional: `pytesseract`, `pywinauto`, `pymobiledevice3`.

## License

MIT — see repo README.
