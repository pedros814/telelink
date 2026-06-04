# TeleLink setup — guide for AI agents

**Audience:** Cursor, Claude Code, Copilot, or any assistant helping a user install TeleLink on Windows.

**Goal:** Get TeleLink running end-to-end with the least friction. Ask only what you need. Run commands yourself when you have shell access.

**Also read:** [SKILL.md](SKILL.md) · [reference.md](reference.md) · [README.md](../../../README.md)

---

## How to talk to the user

| Do | Don't |
|----|--------|
| One short question, then act | Dump a 20-item checklist |
| Say what you're doing and why in one line | Explain every config key upfront |
| Offer **Skip** / **Later** for optional features | Require GitHub or tunnels on day one |
| Run `setup.ps1`, `config`, `watcher` for them when possible | Ask them to hand-edit YAML for things `config edit` can do |
| Confirm success with a quick test (`caught`, `config`) | Assume setup worked without checking |

**Tone:** Direct, calm, human. Example: *"Quick one — what's your first name for SMS shortcuts? (e.g. Alex)"*

---

## What TeleLink needs (tiers)

| Tier | Needed for | User must provide |
|------|------------|-------------------|
| **Core** | Watcher, `caught`, `send`, contacts | Windows + Phone Link paired, Python install, **owner** block, notification permission |
| **Outtake** | `outtake` with files → QR on phone | **GitHub token** (or URL-only outtake without uploads) |
| **Intake** | Phone → PC over Wi‑Fi | Same Wi‑Fi; firewall allow Python; optional **intake token** |
| **Intake global** | Phone → PC from anywhere | **cloudflared** or **ngrok** on PATH |
| **Auto-send** | Agents tap Send in Phone Link | `messaging.method: auto` (default in example); may still need a tap on iPhone |

Everything else can stay at defaults.

---

## Setup flow (follow in order)

### Phase 0 — Can we run TeleLink at all?

**Check (ask only if unknown):**

1. Windows 10/11?
2. iPhone paired in **Phone Link** (Link to Windows) with **Messages** and **Photos** enabled?

If no Phone Link → stop and help them pair first. TeleLink cannot work without it.

**Repo path:** Note the folder path (e.g. `C:\Users\...\Telelink CLI`). All commands run from there.

---

### Phase 1 — Install (you run this)

```powershell
cd "C:\path\to\Telelink CLI"
.\scripts\setup.ps1
```

This creates `.venv`, installs `requirements.txt`, copies `config.example.yaml` → `config.yaml`, and seeds `data/contacts.jsonl` if missing.

**If Python missing:** Send them to https://www.python.org/downloads/ — check **Add python.exe to PATH**, then re-run setup.

**Verify:**

```powershell
.\.venv\Scripts\Activate.ps1
python -m telelink config
```

You should see paths, intake URL placeholder, harvest status. If import errors → re-run `setup.ps1`.

---

### Phase 2 — Owner identity (required, ~2 min)

Owner lives in **`config.yaml`** under `owner:` — not in contacts. Use CLI when guiding:

| Ask user | Config key | `config edit` alias |
|----------|------------|---------------------|
| Business or brand name (or "none" → use personal) | `owner.business_name` | `business` |
| First name / short name | `owner.personal_name_short` | — use `config edit owner.personal_name_short …` |
| Full name (optional) | `owner.personal_name_full` | — |
| Work email (optional) | `owner.work_email` | — |
| Timezone (default America/Denver if unsure) | `owner.timezone` | — |
| How should AI draft your texts? (one sentence) | `owner.talking_tone` | `tone` |

**Minimal script (batch if user prefers):**

> I need four things for your profile: **business name**, **first name**, **email** (optional), and **how you want texts to sound** (e.g. "Professional, direct, no em dashes"). Reply in one message or say "use defaults" and I'll only set name + business.

**Apply example:**

```text
config edit business YourCo
config edit owner.personal_name_short Alex
config edit tone Professional, direct, human tone. No em dashes.
```

---

### Phase 3 — Notifications (required for watcher)

```powershell
start ms-settings:privacy-notifications
```

Tell the user: turn **Notifications** on for **Python** and/or **Windows Terminal** (whichever runs TeleLink). Recommend **`start.bat`** (runs elevated) if toasts never appear.

**Smoke test:**

```powershell
python -m telelink watcher
```

Ask them to send a test iMessage to themselves or receive any toast. Then:

```powershell
python -m telelink caught last 3
```

If empty → privacy settings, watcher window still open, Phone Link running, try admin (`start.bat`).

```powershell
python -m telelink watcher stop
```

---

### Phase 4 — Contacts (when they care about names / routing)

Contacts file: **`data/contacts.jsonl`** (not config).

**Ask only if they use `send` or want contact tags on notifications:**

> Anyone you text often? Give **name** + **phone** (E.164 if possible), one per line — or say **skip** and we'll add later.

```text
contacts add "Client Name" +15551234567
sync --caught
```

Optional: `routing.only_contacts: true` — only if they want to **ignore** non-contact toasts.

---

### Phase 5 — Optional features (gate with one question each)

Ask once:

> Do you want **PC → phone file sharing** (QR via GitHub), **phone → PC uploads** (Wi‑Fi form), or **none for now**?

#### 5a — Outtake (GitHub) — only if they want file/QR sharing

**Ask:**

> For QR file sharing I need a **GitHub personal access token** with `repo` scope. Create one at https://github.com/settings/tokens — paste it here (I'll put it in config, not in chat logs you share publicly). Or say **skip**.

**Never** commit tokens. Prefer env var on their machine:

```powershell
$env:GITHUB_TOKEN = "ghp_..."
```

Or:

```text
config edit github_token ghp_xxxxxxxx
config edit owner nicholasxdavis
```

(`owner` under outtake = GitHub username; empty = auto from token.)

Default repo name: `telelink-sharing` (auto-created). Confirm:

```powershell
python -m telelink outtake https://example.com
```

(URL-only works without token; **file upload** needs token.)

#### 5b — Intake (LAN) — only if phone → PC

Usually **no secrets**. Defaults: port **8787**, bind `0.0.0.0`.

**Tell user:**

1. PC and iPhone on **same Wi‑Fi**
2. Allow **Python** through Windows Firewall (Private network)
3. Run `intake` → scan QR or open `http://<LAN-IP>:8787/`

**Optional — only if they want the form locked down:**

> Want a password on the intake page? Say a short secret or **no**.

```text
config edit token their-secret-here
```

Phone/Shortcut must send header `X-Telelink-Token` or `Authorization: Bearer …` — see `assets/iphone-intake.txt`.

**iOS Shortcut:** Point them to **`assets/iphone-intake.txt`** (step-by-step). You can read that file and walk them through 3–4 steps, not the whole doc at once.

#### 5c — Intake global — only if LAN is not enough

Needs **cloudflared** or **ngrok** installed. Ask:

> Need intake from outside your home Wi‑Fi? I'll need **cloudflared** or **ngrok** on your PC — which do you have, or should we skip?

```text
intake global
```

Config: `intake.global_tunnel` (`auto` | `cloudflared` | `ngrok`).

---

## Question cheat sheet (copy-paste friendly)

Use **one** of these per message:

1. **Phone Link:** "Is your iPhone already paired in Phone Link with messages on? (yes/no)"
2. **Path:** "Where did you clone TeleLink? (folder path)"
3. **Owner:** "What first name and business name should I put in config?"
4. **Tone:** "One line: how should texts sound when an AI drafts them?"
5. **Notifications:** "Can you open Settings → Notifications and allow Python/Terminal? Say done when ready."
6. **Outtake:** "Want QR file sharing? If yes, paste a GitHub token with repo scope, or say skip."
7. **Intake:** "Want a Wi‑Fi upload page from your phone? (yes/skip)"
8. **Intake lock:** "Password on that page? (word or no)"
9. **Contacts:** "Anyone to add for send by name? name + phone, or skip."

---

## Commands to prefer over hand-editing files

| Task | Command |
|------|---------|
| Set most config | `config edit <alias> <value>` |
| Dashboard | `config` or `doctor` |
| Read one key | `config get owner.talking_tone` |
| Add contact | `contacts add "Name" +1…` |
| Test capture | `watcher` → `caught` |
| Test intake | `intake --qr` |
| In-app help | `how` · `help intake` |

**Aliases:** `business`, `tone`, `port`, `token`, `github_token`, `analyze_screenshot`.

---

## Verification checklist (agent runs before saying "you're done")

- [ ] `python -m telelink config` runs without errors
- [ ] `owner.personal_name_short` and `owner.business_name` set
- [ ] `watcher` + test notification → row in `caught`
- [ ] `send` opens Phone Link compose (user confirms; auto-send is best-effort)
- [ ] If outtake wanted: `outtake <small-file>` or URL test succeeds
- [ ] If intake wanted: `intake --qr`, phone can open LAN URL
- [ ] No secrets pasted into git-tracked files the user might commit — warn if `config.yaml` has tokens

**Daily use reminder for user:**

```text
watcher          # leave open while working
caught           # see what arrived
send "Name" …    # reply
watcher stop     # when done
```

Or double-click **`start.bat`** for admin shell.

---

## Files you must know

| Path | Role |
|------|------|
| `config.yaml` | Owner, intake, outtake, messaging, analyze |
| `data/contacts.jsonl` | People + `match` rules |
| `data/caught.jsonl` | Notification log |
| `data/.analyze/latest.json` + `latest.png` | AI vision snapshot (short TTL) |
| `assets/iphone-intake.txt` | iOS Shortcut walkthrough |
| `assets/contacts.example.jsonl` | Contact row shape |
| `.cursor/skills/telelink/` | Agent skill (copy to `~/.cursor/skills/telelink/` for all projects) |

---

## Security (non-negotiable)

- Do **not** commit `config.yaml` if it contains `outtake.github.token`, `intake.token`, or pasted PATs.
- Prefer **`GITHUB_TOKEN`** env var over committing tokens.
- Do **not** repeat the user's token back in full in the chat if avoidable; confirm "token saved" instead.
- If user pasted a token in a public thread, tell them to **revoke and rotate** on GitHub.

---

## Troubleshooting (quick)

| Symptom | Fix |
|---------|-----|
| No `caught` rows | Notification privacy, watcher open, Phone Link running, try `start.bat` |
| `send` wrong person | `contacts` + `match` patterns, `sync` |
| Intake won't load on phone | Same Wi‑Fi, firewall, `config` shows LAN URL |
| Outtake upload fails | Token scope `repo`, network, `config get outtake.github` |
| Agent can't see images | `config get analyze.screenshot` — read `data/.analyze/latest.json` then `latest.png` within TTL |
| Import / module errors | `.\scripts\setup.ps1`, activate `.venv` |

---

## When setup is "good enough"

**Minimum viable:** Phases 0–3 done — watcher + `caught` + owner + `send` opens compose.

**Full stack:** Above + GitHub outtake + intake on LAN + a few contacts + optional Shortcut.

Stop asking when the user's stated goal works. Offer `how` or `help <topic>` for anything they skipped.

---

## Example first message (agent → user)

> I'll get TeleLink set up with you — usually about 10 minutes. First: is your iPhone already paired in **Phone Link** on this PC, with messages syncing? (yes/no)

Then proceed phase by phase. No need to mention every feature upfront.
