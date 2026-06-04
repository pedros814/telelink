# TeleLink — AI agent quick reference

**Do not explore the codebase first.** Run commands from this repo root.

```powershell
.\telelink.ps1 agent context    # JSON: tone, recent messages, analyze paths, exact commands
.\telelink.ps1 agent            # this cheat sheet as text
```

Full skill (setup, config, dev): `.cursor/skills/telelink/SKILL.md`

---

## Run commands

| Shell | Command |
|-------|---------|
| Shortcut | `.\telelink.ps1 <cmd>` |
| Direct | `.\.venv\Scripts\python.exe -m telelink <cmd>` |

Windows only. Phone Link must be paired. Watcher optional for `convo` / `received`; required for live `caught`.

---

## Task → command (copy-paste)

| User wants | Run this |
|------------|----------|
| **What did [name] send me?** | `.\telelink.ps1 received mom` |
| Last N messages **from** someone | `.\telelink.ps1 received last 5 mom` |
| Read full SMS thread (both directions) | `.\telelink.ps1 convo mom --raw` |
| List recent SMS threads | `.\telelink.ps1 convo threads` |
| Read phone notifications | `.\telelink.ps1 caught --raw --limit 10` |
| See last attachment (vision) | Read `data/.analyze/latest.json` then `data/.analyze/latest.png` |
| Send SMS now | `.\telelink.ps1 send "Contact Name" Your message here` |
| Schedule SMS later | `.\telelink.ps1 send in%2hour% "Contact" Your message` |
| List contacts | `.\telelink.ps1 contacts` |
| Missed calls | `.\telelink.ps1 missed` |
| Share file to phone | `.\telelink.ps1 outtake C:\path\to\file.pdf` |
| Auto-reply session with someone | `.\telelink.ps1 ars start {session} {who}` then `ars next {session} --raw` — see `.skills/telelink/ARS.md` |

### “What did my mom send me?”

Use **`received`**, not `convo` alone:

```powershell
.\telelink.ps1 received mom
```

- Resolves **mom**, **Mom?**, **Mom🩵**, etc. via contacts + match rules
- Returns **one JSON object** with full message bodies (not truncated tables)
- Only **incoming** messages (what they sent you)

`--raw` on `convo` is JSONL for the whole thread; flags work after the contact: `convo mom --raw`, `convo last 10 mom --raw`.

---

## Send SMS (agents)

1. Run `.\telelink.ps1 agent context` — use `owner.talking_tone` when drafting (do **not** paste `@tone` into the message).
2. Resolve contact: `.\telelink.ps1 contacts` or use `+1…` number.
3. Send: `.\telelink.ps1 send "Name" message body`

`messaging.method: auto` clicks Send in Phone Link (best-effort).

---

## Read messages — three sources

| Source | Command | What it is |
|--------|---------|------------|
| **What they texted (SMS)** | `received <who>` | Incoming only, full text, agent JSON |
| **Full SMS thread** | `convo <who> --raw` | In + out, Phone Link history |
| **Notifications** | `caught --raw` | Toasts from any app |

For “what did they text?” → **`received`**. For “show the whole conversation” → **`convo --raw`**. For “what notification just arrived?” → **`caught --raw`**.

---

## Vision workflow

When the last catch had an image:

1. `data/.analyze/latest.json` — sender, channel, timestamp
2. `data/.analyze/latest.png` — centered preview (~700×500, TTL ~4m)

Do not open `data/attachments/` unless full resolution is needed.

---

## Do not

- Search `telelink/*.py` before running the command above
- Use `convo` without `--raw` when you need full message text (tables truncate)
- Put `--raw` before the contact (`mom --raw` is correct; `convo last 10 mom --raw` works)
- Assume Mac/Linux — Windows + Phone Link only
- Commit secrets from `config.yaml`
