# ARS — Auto Reply Session

> TeleLink decides IF to reply; you (the agent) decide WHAT to say.

ARS is a CLI-driven polling loop that watches one SMS contact thread and tells you when a reply is needed. You draft and send the SMS yourself using the same `send`, `convo`, and `received` commands you already know.

**Do not read `data/ars/` files.** Use only the CLI commands below.

---

## When the user says X, run Y

| User says | Agent runs |
|-----------|------------|
| "Start an ARS with Client" | `.\telelink.ps1 ars start client-ars Client` then `ars next client-ars --raw` |
| "Keep auto-reply going for Mom" | `.\telelink.ps1 ars list --raw` → if missing, `ars start mom-ars mom` → `ars next mom-ars --raw` |
| "Stop ARS for client" | `.\telelink.ps1 ars stop client-ars` |
| "Check if anyone texted" | `.\telelink.ps1 ars next <session> --raw` for each active session |

Default session slug: `<contact-slug>-ars` (e.g. `mom-ars`, `client-ars`).

---

## Command reference

| Step | Command | Purpose |
|------|---------|---------|
| 0 | `.\telelink.ps1 agent context` | Tone + global hints |
| 1 | `.\telelink.ps1 ars start <session> <contact>` | Start session (+ background window) |
| 2 | `.\telelink.ps1 ars next <session> --raw` | **Primary:** what to do now + exact follow-up commands |
| 2b | `.\telelink.ps1 ars status <session> --raw` | Poll state without advancing (optional) |
| 3a | `.\telelink.ps1 convo "<contact>" --raw` | Full thread when `action` is `reply` |
| 3b | `.\telelink.ps1 received <contact>` | Last inbound only (lighter) |
| 4 | *(agent thinks — not a TeleLink command)* | Draft SMS using `talking_tone` |
| 5 | `.\telelink.ps1 send "<contact>" <message>` | Send SMS |
| 6 | `.\telelink.ps1 ars ack <session>` | Close the turn |
| · | `.\telelink.ps1 ars list --raw` | See active sessions |
| · | `.\telelink.ps1 ars stop <session>` | End session |
| · | `.\telelink.ps1 ars wait <session> --raw` | Block until reply needed |
| · | `.\telelink.ps1 ars pause <session>` | Pause polling |
| · | `.\telelink.ps1 ars resume <session>` | Resume polling |

---

## `ars next --raw` schema

### When `action` is `reply`

```json
{
  "session": "client-ars",
  "state": "need_reply",
  "action": "reply",
  "needs_tending": true,
  "reason": "inbound_after_last_outbound",
  "contact": {
    "query": "Client",
    "name": "Client",
    "phone": "+15551234567"
  },
  "pending_inbound": {
    "at": "2026-06-01T18:02:00-06:00",
    "body_preview": "How was your day?",
    "id": "msg-…"
  },
  "commands": {
    "tone": ".\\telelink.ps1 agent context",
    "thread": ".\\telelink.ps1 convo \"Client\" --raw",
    "inbound": ".\\telelink.ps1 received Client",
    "send": ".\\telelink.ps1 send \"Client\" <draft your message here>",
    "ack": ".\\telelink.ps1 ars ack client-ars"
  },
  "agent_rules": [
    "Draft the send body yourself using owner.talking_tone from agent context",
    "Do not paste @tone into the SMS",
    "Do not read data/ars/ files — use these commands only"
  ]
}
```

### When `action` is `wait`

```json
{
  "session": "client-ars",
  "state": "waiting",
  "action": "wait",
  "needs_tending": false,
  "reason": "already_replied",
  "contact": { "name": "Client", "phone": "+1…" },
  "commands": {
    "poll": ".\\telelink.ps1 ars next client-ars --raw",
    "status": ".\\telelink.ps1 ars status client-ars --raw"
  },
  "poll_after_seconds": 45
}
```

---

## Continuous Autonomous loop

Instead of polling and sleeping, you should use `ars wait` as a background command to keep your session alive and react instantly:

```
loop:
  # ars wait blocks in the background until the user replies
  j = ars wait SESSION --raw
  if j.action == "stopped": break
  if j.action == "reply":
    run j.commands.tone, j.commands.thread  # parse JSON stdout
    draft = <agent LLM>
    run send with draft
    run j.commands.ack
```

When you run `ars wait` as an async/background command, you can stop calling tools. The system will automatically wake you up the exact second the contact replies, providing the JSON output. This prevents dropped sessions and avoids polling!

---

## Drafting rules

1. Run `.\telelink.ps1 agent context` — use `owner.talking_tone`.
2. Read the thread via `convo --raw` or `received`.
3. Draft the SMS in your own words.
4. Do **not** paste `@tone` into the message text.
5. Use `/n` for newlines in SMS (not `\n`).

---

## Needs-tending (what "reply" means)

TeleLink checks the thread and returns `action: reply` when:
- There is an inbound message newer than the last outbound (you haven't replied yet)
- You never replied at all
- It is not just a tapback/reaction ("Liked …", "Emphasized …")
- The message is not stale (older than 72h by default)

---

## Stop waiting

After you run `send` and `ack`, the next `ars next` returns `action: wait`. ARS also auto-detects outbound via `sent.jsonl` and the convo thread — if you forget `ack`, it will still notice you replied within 1-2 ticks.

---

## Messaging integration

ARS uses the same `send` command as everything else in TeleLink.

- `messaging.method: auto` — clicks Send in Phone Link automatically.
- `messaging.method: manual` — opens compose only; you confirm send on phone. Use `ars ack --force` after manual send.
- `messaging.enabled: false` — ARS returns `action: error`.

---

## Troubleshooting

| Problem | Fix |
|---------|----- |
| Empty thread | Run `.\telelink.ps1 sync`, open Phone Link Messages |
| Verify failed after send | Wait 1-2 ticks; ARS will detect via convo poll |
| `stale_agent: true` in next JSON | Re-run the full loop (convo → send → ack) |
| `superseded_pending: true` | Contact texted again — re-read thread before sending |

---

## Examples

### Start ARS for Client

```powershell
.\telelink.ps1 agent context
.\telelink.ps1 ars start client-ars Client
.\telelink.ps1 ars next client-ars --raw
# If action == "reply":
.\telelink.ps1 convo "Client" --raw
# Agent thinks → drafts SMS
.\telelink.ps1 send "Client" Sounds good — I'll send that over this afternoon.
.\telelink.ps1 ars ack client-ars
.\telelink.ps1 ars next client-ars --raw
# If action == "wait" → done for now
```

### Stop ARS

```powershell
.\telelink.ps1 ars list --raw
.\telelink.ps1 ars stop client-ars
```

---

## Do not

- Read `data/ars/*.json` — use `ars next --raw` only
- Read the ARS window output — it's for humans, not agents
- Generate reply text inside TeleLink — you draft it yourself
- Run `ars` without `--raw` when you need machine-readable output
