"""Terminal how-to guide for TeleLink — skill-style docs, baby-blue theme."""

from __future__ import annotations

import textwrap
from typing import Callable

from telelink import chalk, ink_ui
from telelink.table import Table

MARGIN = ink_ui.MARGIN
_WRAP = 68


def _indent_block(text: str) -> str:
    return ink_ui.indent(text, margin=MARGIN)


def _plain(text: str) -> str:
    wrapped = textwrap.fill(text, width=_WRAP, subsequent_indent="  ")
    return _indent_block(chalk.plain(wrapped))


def _heading(title: str) -> str:
    rule = chalk.muted("─" * 52)
    return f"{MARGIN}{chalk.label(title)}\n{MARGIN}{rule}"


def _step(n: int, text: str) -> str:
    return f"{MARGIN}{chalk.baby(f'{n}.')}  {chalk.plain(text)}"


def _bullet(text: str) -> str:
    return f"{MARGIN}{chalk.baby('·')}  {chalk.plain(text)}"


def _cmd(line: str) -> str:
    return f"{MARGIN}  {chalk.command(line)}"


def _file(line: str) -> str:
    return f"{MARGIN}  {chalk.value(line)}"


def _hero() -> str:
    title = chalk.baby.bold()("TeleLink")
    tagline = chalk.muted("how to use")
    return "\n".join(
        [
            "",
            f"{MARGIN}{title}  {tagline}",
            _plain(
                "Capture Phone Link notifications on Windows, match them to your "
                "contacts, and review everything from this shell. Data stays on your machine."
            ),
        ]
    )


def _flow_diagram() -> str:
    flow = chalk.value(
        "iPhone  →  Phone Link  →  watcher  →  caught.jsonl  +  attachments  +  .analyze/"
    )
    return f"{MARGIN}{flow}"


def _section_overview() -> str:
    lines = [
        _heading("What TeleLink does"),
        _flow_diagram(),
        "",
        _bullet("Watches Windows toast notifications from Phone Link / Your Phone."),
        _bullet("Copies new images from Phone Link folders into data/attachments/."),
        _bullet(
            "Writes a short-lived AI snapshot (data/.analyze/latest.png) when attachments arrive."
        ),
        _bullet("Tags each message with a contact + channel when match rules hit."),
        _bullet("Unmatched senders go to routing.unmatched_label (default: unassigned)."),
    ]
    return "\n".join(lines)


def _section_quick_start() -> str:
    lines = [
        _heading("Quick start"),
        _step(1, "Pair iPhone with Phone Link (messages + photos enabled)."),
        _step(2, "Run setup once: .\\scripts\\setup.ps1"),
        _step(3, "Set owner info (config edit) and add contacts in data/contacts.jsonl:"),
        _cmd("config edit business YourCo"),
        _cmd("config edit nameshort Alex"),
        _step(4, "Allow notification access for Python / Terminal:"),
        _cmd("start ms-settings:privacy-notifications"),
        _step(5, "Launch TeleLink (start.bat) and start the watcher:"),
        _cmd("watcher"),
        _step(6, "Send a test text to your PC. Browse with:"),
        _cmd("caught"),
    ]
    return "\n".join(lines)


def _section_daily() -> str:
    lines = [
        _heading("Daily workflow"),
        _plain(
            "TeleLink splits work across two windows: this shell for commands, "
            "and a separate watcher window that must stay open while you want capture live."
        ),
        "",
        _bullet("watcher — open the capture window (only when you need it)."),
        _bullet("caught — read what was captured (table, json, or filters)."),
        _bullet("send — compose SMS via Phone Link to a contact or +number."),
        _bullet("contacts — view or add people and match rules."),
        _bullet("config — status view (paths, folders, intake URL)."),
        _bullet("config edit <key> <value> — change config.yaml without an editor."),
        _bullet("watcher stop — force-close the watcher when you are done."),
        _bullet("calls / missed — call log from Phone Link toasts (watcher must be running)."),
        _bullet("sync — re-sync Phone Link contacts and clear stale caches (auto every 15m)."),
    ]
    return "\n".join(lines)


def _section_commands() -> str:
    table = Table(
        head=["Command", "What it does"],
        col_widths=[18, 44],
        value_cols=[1],
    )
    rows: list[tuple[str, str]] = [
        ("watcher", "Start capture in a new console window"),
        ("watcher stop", "Force stop the watcher window"),
        ("caught", "Browse notifications (default table)"),
        ("caught contacts", "Only rows matched to a contact"),
        ("caught last 5", "Five most recent"),
        ("caught json", "Full JSON field table"),
        ("caught group channel", "Group by platform (iMessage, SMS, …)"),
        ("contacts", "Contacts table"),
        ("contacts add Name +1…", "Save or update a contact"),
        ("send <who> <msg>", "Open SMS compose in Phone Link"),
        ("sync", "Re-sync Phone Link + contacts (auto every 15m)"),
        ("sync --caught", "Re-sync + import phone senders from caught log"),
        ("config", "Status — paths, folders, contacts, intake URL"),
        ("config edit <key> <val>", "Set config.yaml (auto-save)"),
        ("config get <key>", "Print one setting"),
        ("config list", "All keys and current values"),
        ("config reset", "Restore config.yaml from config.example.yaml"),
        ("intake", "LAN server — share via QR or SMS"),
        ("intake global", "Public URL via cloudflared/ngrok"),
        ("intake stop", "Stop intake server and tunnel"),
        ("outtake <url|file…>", "QR — link or share file(s) via GitHub (multi-file → zip)"),
        ("calendar", "Scheduled SMS — list, add, delay, delete"),
        ("calendar status", "Calendar health + Google sync"),
        ("calls", "Recent Phone Link calls (1d log)"),
        ("missed", "Missed calls only"),
        ("convo mom", "SMS thread from Phone Link phone.db"),
        ("convo last 5 mom", "Last N messages with a contact"),
        ("convo threads", "List recent Phone Link threads"),
        ("status", "Quick caught summary"),
        ("wipe <target>", "Clear local data (caught, calls, sent, contacts, …)"),
        ("wipe all --yes", "Reset all data/ files; keeps config.yaml"),
        ("how", "This guide"),
        ("help", "Short command list"),
    ]
    for cmd, desc in rows:
        table.push([cmd, desc])
    return "\n".join([_heading("Commands"), _indent_block(table.to_string())])


def _section_send_shortcuts() -> str:
    from telelink.classify import get_owner
    from telelink.messaging import owner_send_tag_help

    try:
        from telelink.config import load_config

        owner = get_owner(load_config())
    except OSError:
        owner = {}

    table = Table(
        head=["Type in message", "config.yaml key", "Your value"],
        col_widths=[22, 22, 18],
        value_cols=[0, 2],
    )
    for tags_display, config_key, label in owner_send_tag_help():
        val = owner.get(config_key)
        shown = str(val).strip() if val is not None and str(val).strip() else chalk.muted("(not set)")
        table.push([tags_display, config_key, shown])

    lines = [
        _heading("Send message shortcuts"),
        _plain(
            "In send <who> <msg>, @tags expand from owner: in config.yaml before the SMS opens. "
            "Tags are case-insensitive."
        ),
        "",
        _indent_block(table.to_string()),
        "",
        _bullet("/n — newline (spaces around /n are trimmed)."),
        _cmd('send +1575… Thanks for calling /n — @nameshort'),
        _plain("Example above becomes two lines ending with your short name."),
        "",
        _heading("Schedule from send"),
        _plain(
            "Prefix with in%<when>% to schedule instead of sending now. "
            "Case-insensitive. Optional % around contact: send in%2hour% %girlfriend% Hey bro."
        ),
        _cmd("send in%2hour% girlfriend Hey bro this is an example"),
        _cmd("send in20s myself quick ping"),
        _cmd('send in%2pm today% "Mom" Running 10 minutes late'),
        _cmd("send girlfriend Hey bro"),
        _plain("Last line sends immediately — same as before."),
    ]
    return "\n".join(lines)


def _section_config() -> str:
    from telelink.messaging import owner_send_tag_help

    alias_rows = [
        ("business", "owner.business_name"),
        ("email", "owner.work_email"),
        ("port", "intake.port"),
        ("token", "intake.token"),
        ("github_token", "outtake.github.token"),
        ("messaging.enabled", "messaging.enabled"),
        ("analyze_screenshot", "analyze.screenshot"),
        ("analyze_ttl", "analyze.ttl"),
        ("analyze", "analyze.screenshot"),
    ]
    table = Table(
        head=["Alias / command", "Maps to"],
        col_widths=[24, 38],
        value_cols=[0, 1],
    )
    for alias, path in alias_rows:
        table.push([alias, path])

    tag_hints = ", ".join(
        tags_display.split(",")[0].strip()
        for tags_display, _cfg_key, _label in owner_send_tag_help()
    )

    lines = [
        _heading("Config — edit from the shell"),
        _plain(
            "Most TeleLink settings live in config.yaml. Use config edit to change a value "
            "from this shell — it saves immediately and reloads the running session. "
            "Plain config (no subcommand) is only the status dashboard."
        ),
        "",
        _cmd("config edit business Your Business"),
        _cmd("config edit intake.port 9000"),
        _cmd("config edit messaging.enabled false"),
        _cmd("config get business"),
        _cmd("config list"),
        _cmd("config reset"),
        "",
        _indent_block(table.to_string()),
        "",
        _bullet(f"Owner @tags in send also map here ({tag_hints})."),
        _bullet("Full dotted paths always work: owner.timezone, outtake.github.repo"),
        _bullet("Booleans: true / false / on / off"),
        _bullet("Lists: comma-separated (urgent,asap) or JSON [\"a\",\"b\"]"),
        _bullet("Contacts stay in data/contacts.jsonl — not config edit."),
        "",
        _plain("config alone (or doctor) prints paths, watch folders, harvest, and intake URL."),
    ]
    return "\n".join(lines)


def _section_contacts() -> str:
    lines = [
        _heading("Contacts & matching"),
        _plain(
            "People live in data/contacts.jsonl — not in config.yaml. "
            "Each contact can have match patterns (name fragments, phone digits, handles)."
        ),
        "",
        _file('{"name": "Shawk", "phone": "+1…", "match": ["shawk"], "platform": "imessage"}'),
        "",
        _bullet("managed: true — notifications can tag this contact."),
        _bullet("managed: false — personal (e.g. yourself); send only, no matching."),
        _bullet("routing.only_contacts: true — skip notifications with no contact match."),
        "",
        _plain("owner in config.yaml is you (business / short name) — not a contact row."),
    ]
    return "\n".join(lines)


def _section_data() -> str:
    table = Table(
        head=["Path", "Purpose"],
        col_widths=[28, 34],
        value_cols=[1],
    )
    for path, purpose in [
        ("data/caught.jsonl", "One JSON line per notification"),
        ("data/calls.jsonl", "Phone Link call log (missed/incoming/outgoing)"),
        ("data/contacts.jsonl", "Contacts + match rules"),
        ("data/telelink.db", "SQLite canonical store"),
        ("data/localstorage.json", "Runtime prefs + sync times only (not contacts)"),
        ("data/attachments/", "Copied images & screenshots (full files)"),
        ("data/.analyze/", "AI snapshot — latest.png + latest.json (short TTL)"),
        ("config.yaml", "Owner, routing, folders, intake (local)"),
        ("data/sent.jsonl", "Outbound SMS log (when messaging.log_sent is on)"),
        ("data/notif-seen.txt", "Watcher duplicate-notification filter"),
    ]:
        table.push([path, purpose])
    lines = [
        _heading("Where data lives"),
        _indent_block(table.to_string()),
        "",
        _plain("Clear any of the above (not config.yaml) with wipe — e.g. wipe caught, wipe all --yes."),
        _cmd("help wipe"),
    ]
    return "\n".join(lines)


def _section_analyze() -> str:
    lines = [
        _heading("Analyze folder — AI snapshots"),
        _plain(
            "When analyze.screenshot is enabled (default: true), every caught image or video "
            "attachment produces a small centered preview in data/.analyze/. This is for "
            "Cursor, Claude, and other agents — faster than opening full attachment files."
        ),
        "",
        _bullet("latest.png — fixed path; 700×500 by default, media centered on dark canvas."),
        _bullet("latest.json — sender, channel, task_id, source filename, timestamp."),
        _bullet("Files auto-delete after analyze.ttl (default 4m). Only this folder is pruned."),
        "",
        _cmd("config get analyze.screenshot"),
        _cmd("config edit analyze_screenshot false"),
        _cmd("config edit analyze_ttl 10m"),
        "",
        _plain("Check if active: config (doctor) shows analyze path and ttl, or off."),
        "",
        _heading("For AI assistants"),
        _bullet("If analyze is on, read data/.analyze/latest.json first, then latest.png."),
        _bullet("Do not pull multi-MB files from data/attachments/ unless the user asks."),
        _bullet("If latest.png is missing, screenshot may be disabled or no recent attachment."),
        _bullet("Type help analyze for more."),
    ]
    return "\n".join(lines)


def _section_help_analyze() -> str:
    lines = [
        _heading("Analyze — AI snapshot folder"),
        _plain(
            "TeleLink writes data/.analyze/latest.png whenever a visual attachment is caught "
            "(images, GIF first frame, video first frame if ffmpeg is installed)."
        ),
        "",
        _step(1, "Confirm it is enabled:"),
        _cmd("config get analyze.screenshot"),
        _step(2, "After a photo/message arrives, open:"),
        _plain("  data/.analyze/latest.json  — who sent it, channel, filename"),
        _plain("  data/.analyze/latest.png   — what it looked like (centered preview)"),
        "",
        _heading("Config keys"),
        _bullet("analyze.screenshot — true/false (master switch)."),
        _bullet("analyze.ttl — 4m, 10m, 1h, or off (how long files stay)."),
        _bullet("analyze.width / analyze.height — canvas size (default 700×500)."),
        _bullet("analyze.dir — subfolder name under data/ (default .analyze)."),
        "",
        _cmd("config edit analyze_screenshot false"),
        _cmd("config edit analyze_ttl 4m"),
        "",
        _plain("Watcher terminal preview (Pillow) is separate — see help watcher."),
    ]
    return "\n".join(lines)


def _section_keys() -> str:
    lines = [
        _heading("Shell keys"),
        _indent_block(ink_ui.hint_bars()),
        "",
        _bullet("Type a command at the telelink › prompt."),
        _bullet("caught and contacts open sub-menus with numbered picks."),
        _bullet("Use quotes for multi-word send targets: send \"Shawk\" On my way."),
        _bullet("send @tags and /n — see Send message shortcuts above."),
    ]
    return "\n".join(lines)


def _section_help_watcher() -> str:
    lines = [
        _heading("Watcher — capture live"),
        _plain(
            "The watcher opens a separate console window on your PC. Keep it open while you "
            "want Phone Link notifications and images captured into data/caught.jsonl."
        ),
        "",
        _cmd("watcher"),
        _cmd("watcher stop"),
        "",
        _step(1, "Allow notification access for Python / Terminal (Windows privacy settings)."),
        _cmd("start ms-settings:privacy-notifications"),
        _step(2, "Run watcher from this shell — a new window opens."),
        _step(3, "Send a test text to your PC, then browse with caught."),
        _cmd("caught"),
        "",
        _bullet("Alias: listen (same as watcher)."),
        _bullet("watcher stop force-closes the watcher window."),
        _bullet("No notifications? Run start.bat as admin and confirm the watcher window is open."),
        _bullet("Check paths with config — watch folders and harvest status."),
        _bullet(
            "Inline photo preview uses built-in Pillow (no extra install). "
            "AI snapshots use data/.analyze/ — help analyze."
        ),
    ]
    return "\n".join(lines)


def _section_help_watcher_stop() -> str:
    lines = [
        _heading("Watcher stop"),
        _plain("Force-closes the watcher console window when you are done capturing."),
        "",
        _cmd("watcher stop"),
        "",
        _bullet("Alias: stop, listen-stop (from the main shell)."),
        _bullet("Start again anytime with watcher."),
    ]
    return "\n".join(lines)


def _section_help_caught() -> str:
    lines = [
        _heading("Caught — browse notifications"),
        _plain("Shows what the watcher captured: messages, images, matched contacts, channels."),
        "",
        _cmd("caught"),
        _cmd("caught contacts"),
        _cmd("caught last 5"),
        _cmd("caught json"),
        _cmd("caught group channel"),
        "",
        _bullet("Type caught at the prompt for a numbered sub-menu."),
        _bullet("contacts / clients — only rows matched to a contact."),
        _bullet("group channel — group by platform (iMessage, SMS, Instagram, …)."),
        _bullet("raw / gron — script-friendly JSON output."),
    ]
    return "\n".join(lines)


def _section_help_wipe() -> str:
    from telelink.wipe_data import wipe_target_names

    names = ", ".join(wipe_target_names())
    lines = [
        _heading("Wipe — clear local data"),
        _plain(
            "Deletes TeleLink runtime files under data/. "
            "config.yaml is never touched. Use before sharing the PC or starting fresh."
        ),
        "",
        _cmd("wipe caught"),
        _cmd("wipe calls"),
        _cmd("wipe sent"),
        _cmd("wipe contacts"),
        _cmd("wipe localstorage"),
        _cmd("wipe attachments"),
        _cmd("wipe analyze"),
        _cmd("wipe seen"),
        _cmd("wipe db"),
        _cmd("wipe caught sent"),
        _cmd("wipe all"),
        _cmd("wipe all --yes"),
        "",
        _plain(f"Targets: {names}"),
        "",
        _bullet("caught — data/caught.jsonl (notifications log)"),
        _bullet("calls — data/calls.jsonl (Phone Link call log)"),
        _bullet("sent — data/sent.jsonl (outbound SMS log)"),
        _bullet("contacts — data/contacts.jsonl + SQLite contact rows"),
        _bullet("localstorage — data/localstorage.json (prefs + sync times; not contact data)"),
        _bullet("attachments — everything under data/attachments/"),
        _bullet("analyze — data/.analyze/ AI snapshot files"),
        _bullet("seen — data/notif-seen.txt (duplicate notification filter)"),
        _bullet("db — data/telelink.db (SQLite; contacts, kv, sync log)"),
        _bullet("all — every target above"),
        "",
        _plain("Aliases: tasks → caught  ·  localstore → localstorage  ·  sqlite → db"),
        "",
        _plain("Prompt shows 1 = yes, 2 = no (same as GitHub outtake). Use --yes to skip."),
    ]
    return "\n".join(lines)


def _section_help_config_reset() -> str:
    lines = [
        _heading("Config reset"),
        _plain(
            "Replaces config.yaml with config.example.yaml. "
            "Use when you want factory defaults — tokens, owner, and custom paths are overwritten."
        ),
        "",
        _cmd("config reset"),
        _cmd("config reset --yes"),
        "",
        _bullet("Prompt: 1 = yes, 2 = no (same style as wipe and outtake)."),
        _bullet("Contacts in data/contacts.jsonl are not changed — only config.yaml."),
        _bullet("data/ files are not wiped — use wipe all for that."),
    ]
    return "\n".join(lines)


def _section_help_sync() -> str:
    lines = [
        _heading("Sync — refresh from Phone Link"),
        _plain(
            "Re-imports contacts from Phone Link DB, config.yaml, contacts.jsonl, sqlite, "
            "and optionally caught. Clears stale caches and re-discovers contacts.db."
        ),
        "",
        _cmd("sync"),
        _cmd("sync --caught"),
        "",
        _bullet("Startup sync: sync.on_startup (default true) runs when TeleLink opens."),
        _bullet("Auto-sync runs every sync.auto_sync_interval (default 15m) while TeleLink is open."),
        _bullet("Disable background sync: config edit auto_sync false"),
        _bullet("Change interval: config edit sync_interval 30m"),
        _bullet("contacts sync — import legacy names from config.yaml only."),
        _bullet("contacts sync-caught — pull phone-like senders from caught log."),
    ]
    return "\n".join(lines)


def _section_help_status() -> str:
    lines = [
        _heading("Status — quick summary"),
        _plain("One-screen snapshot: caught count, channels, output paths."),
        "",
        _cmd("status"),
    ]
    return "\n".join(lines)


def _section_help_config_get() -> str:
    lines = [
        _heading("Config get — read one setting"),
        _plain("Prints a single value from config.yaml using a short alias or full path."),
        "",
        _cmd("config get business"),
        _cmd("config get intake.port"),
        "",
        _bullet("See all keys: config list"),
        _bullet("Change a value: config edit <key> <value>"),
    ]
    return "\n".join(lines)


def _section_help_config_list() -> str:
    lines = [
        _heading("Config list — all settings"),
        _plain("Lists every key in config.yaml with its current value, grouped by section."),
        "",
        _cmd("config list"),
        "",
        _bullet("Edit a value: config edit business Your Business"),
        _bullet("Read one value: config get <key>"),
        _bullet("Status dashboard (paths, folders): config"),
    ]
    return "\n".join(lines)


def _section_help_config_edit() -> str:
    body = _section_config()
    extra = "\n".join(
        [
            "",
            _heading("Quick reference"),
            _cmd("config edit <key> <value>"),
            _bullet("Values with spaces: quote them or use underscores in aliases."),
        ]
    )
    return body + extra


def _section_help_intake() -> str:
    lines = [
        _heading("Intake — send TO your PC"),
        _plain(
            "Starts a small web server on your LAN (same Wi-Fi as your phone). "
            "Upload files, paste messages, or share links from your phone browser."
        ),
        "",
        _step(1, "On PC, run intake and pick how to share:"),
        _cmd("intake"),
        _bullet("1 QR — scan with your phone camera."),
        _bullet("2 Text message — opens Phone Link SMS with the intake link."),
        _step(2, "On phone, open the link and use the upload form."),
        _step(3, "Items land in data/caught.jsonl and data/attachments/."),
        "",
        _plain("Flags: intake --qr  ·  --sms  ·  --wait (keep server until Ctrl+C)."),
        _plain("Set intake.token in config.yaml to restrict uploads."),
        _plain("Public internet URL: help intake global"),
        _plain("Shut down: help intake stop  or  intake stop"),
        "",
        _bullet("Phone must be on the same Wi-Fi as this PC for LAN intake."),
        _file("assets/iphone-intake.txt"),
    ]
    return "\n".join(lines)


def _section_help_intake_global() -> str:
    lines = [
        _heading("Intake global — public URL"),
        _plain(
            "Starts intake with a public URL via cloudflared or ngrok (internet, not just LAN). "
            "Uses pyhttpd by default for HTTP range file serving."
        ),
        "",
        _cmd("intake global"),
        _cmd("intake global --qr"),
        _cmd("intake global --wait"),
        "",
        _plain("config edit global_tunnel auto   # cloudflared | ngrok | auto"),
        _plain("config edit global_server pyhttpd   # pyhttpd or stdlib"),
        _plain("Stop: intake stop"),
    ]
    return "\n".join(lines)


def _section_help_intake_stop() -> str:
    lines = [
        _heading("Intake stop"),
        _plain("Shuts down the intake web server and any public tunnel (cloudflared/ngrok)."),
        "",
        _cmd("intake stop"),
    ]
    return "\n".join(lines)


def _section_help_outtake() -> str:
    lines = [
        _heading("Outtake — links or files ON your phone"),
        _plain(
            "Share a URL or PC file to your phone via QR or SMS. Files upload to GitHub; "
            "the QR points at the raw download URL. Multiple files are zipped first. "
            "File uploads ask for confirmation (1 = yes, 2 = no) — they are public on GitHub."
        ),
        "",
        _cmd("outtake www.youtube.com"),
        _cmd("outtake C:\\Users\\you\\Desktop\\brief.pdf"),
        _cmd("outtake report.pdf slide.png notes.txt"),
        "",
        _plain("Set outtake.github in config.yaml (token, owner, repo) or use GITHUB_TOKEN env."),
        _plain("config edit github_token <token>"),
        _plain("Missing repo is created automatically on first upload."),
        _plain(
            "Uploads auto-delete from GitHub after outtake.auto_delete (default 30m), "
            "using each file's last commit date from the GitHub API (filename timestamp as fallback). "
            "Cleanup runs every outtake.auto_delete_poll (default 30m) in watcher and shell."
        ),
        _plain("config edit outtake_auto_delete 1h  ·  config edit outtake_auto_delete off"),
    ]
    return "\n".join(lines)


def _section_help_convo() -> str:
    lines = [
        _heading("Convo — Phone Link message history"),
        _plain(
            "Reads the same SMS/iMessage cache Phone Link uses in the Messages tab "
            "(phone.db under LocalCache/Indexed/…/System/Database). Usually ~30 days "
            "of history. Open Phone Link → Messages and open the thread once if convo "
            "returns empty."
        ),
        "",
        _cmd("convo mom"),
        _cmd("convo 5752701276"),
        _cmd("convo +15559876543"),
        _cmd("convo last 5 mom"),
        _cmd("convo today mom"),
        _cmd("convo yesterday mom"),
        _cmd("convo all mom"),
        _cmd("convo 7d mom"),
        _cmd("convo threads"),
        _cmd("convo mom --json"),
        _cmd("convo mom --raw"),
        "",
        _heading("Fallback"),
        _plain(
            "Android may cache threads in phone.db. iPhone often does not — TeleLink reads "
            "visible messages from the Phone Link window (keep Messages open on the thread). "
            "Then sent.jsonl (outbound) and caught.jsonl (notification snippets)."
        ),
        "",
        _heading("Config"),
        _plain("config edit convo_enabled false"),
        _plain("convo.ui_fallback: true — read Phone Link UI when phone.db missing (default)"),
        _plain("convo.default_limit in config.yaml (default 50)"),
    ]
    return "\n".join(lines)


def _section_help_calls() -> str:
    lines = [
        _heading("Calls — Phone Link call log"),
        _plain(
            "TeleLink imports call history from Phone Link calling.db (same data as the "
            "Calls tab) and can also capture live call toasts when the watcher is running. "
            "Run sync or calls sync to refresh. Entries older than calls.ttl (default 1 day) "
            "are removed from data/calls.jsonl — raise calls_ttl if Phone Link shows older missed calls."
        ),
        "",
        _cmd("calls"),
        _cmd("calls 20"),
        _cmd("missed"),
        _cmd("missed 10"),
        "",
        _heading("Reminders"),
        _plain(
            "While the intake server is running, the periodic INTAKE reminder also shows "
            "how many missed calls are in the log (e.g. still running · up 12m · 2 missed calls)."
        ),
        _plain(
            "Every calls.remind_interval (default 10m), the shell prints a CALLS label when "
            "missed calls exist or intake is live."
        ),
        "",
        _heading("Config"),
        _plain("config edit calls_ttl 2d       — keep log longer"),
        _plain("config edit calls_ttl 12h      — shorter retention"),
        _plain("config edit calls_enabled false — disable call capture"),
        _plain("config edit calls_remind 15m   — reminder interval"),
        "",
        _bullet("Call rows are not duplicated into caught — use calls / missed for call history."),
        _bullet("wipe calls — clear the call log."),
    ]
    return "\n".join(lines)


def _section_help_calendar() -> str:
    lines = [
        _heading("Calendar — schedule SMS"),
        _plain(
            "Schedule messages to send later via Phone Link. Events fire automatically while "
            "TeleLink is running (shell or watcher). Every 15 minutes the shell shows how many "
            "events are pending — only when there is at least one."
        ),
        "",
        _cmd("calendar"),
        _cmd('calendar add love-note girlfriend "in 3h" "I love you baby! — funny quote here"'),
        _cmd('calendar add dinner-reminder "Mom" "2pm today" "Running 10 min late"'),
        _cmd("calendar delay love-note 30m"),
        _cmd("calendar delete love-note"),
        _cmd("calendar love-note status"),
        _cmd("calendar status"),
        "",
        _heading("Time expressions"),
        _bullet("in 3h · in 45m · in 20s · in20s · 30m (delay shorthand)"),
        _bullet("2pm today · today 2pm · tomorrow 9am"),
        _bullet("ISO: 2026-05-28T14:00 (uses owner.timezone)"),
        "",
        _heading("Agents / AI"),
        _plain(
            "When the user asks to send a message at a specific time, draft the SMS using "
            "owner.talking_tone, then run calendar add with a short name slug, contact, when, "
            "and the final message body."
        ),
        "",
        _heading("Google Calendar (optional)"),
        _plain("Full two-way sync — edits in Google or TeleLink stay in sync."),
        _plain("config edit google_calendar true"),
        _plain("config edit google_credentials path/to/oauth-client.json"),
        _cmd("calendar connect google"),
        _cmd("calendar sync"),
        _plain("pip install google-api-python-client google-auth-oauthlib"),
    ]
    return "\n".join(lines)


def _section_help_ars() -> str:
    lines = [
        _heading("ARS — Auto Reply Session"),
        _plain(
            "ARS watches one contact thread and tells an agent when a reply is needed. "
            "The agent drafts and sends the SMS via the same send command."
        ),
        "",
        _cmd("ars start client-ars Client"),
        _cmd("ars next client-ars --raw"),
        _cmd("ars ack client-ars"),
        _cmd("ars stop client-ars"),
        _cmd("ars list --raw"),
        _cmd("ars pause client-ars"),
        _cmd("ars resume client-ars"),
        _cmd("ars wait client-ars --raw"),
        "",
        _heading("Agent loop"),
        _step(1, "ars start <session> <contact> — starts background window"),
        _step(2, "ars next <session> --raw — returns JSON with action (reply/wait/stopped)"),
        _step(3, "If action=reply: convo/received → draft SMS → send → ars ack"),
        _step(4, "ars next again — loops until stopped"),
        "",
        _heading("Config"),
        _bullet("ars.poll_interval — how often to check (default 45s)"),
        _bullet("ars.cooldown — debounce after reply (default 30s)"),
        _bullet("ars.ignore_stale_hours — skip old messages (default 72h)"),
        _bullet("ars.thread_limit — max messages to fetch (default 50)"),
        _bullet("ars.enabled — master switch (default true)"),
        "",
        _plain("Full agent playbook: .skills/telelink/ARS.md"),
    ]
    return "\n".join(lines)


def _section_intake_outtake() -> str:
    return "\n\n".join([_section_help_intake(), _section_help_outtake()])


def _section_troubleshoot() -> str:
    lines = [
        _heading("Troubleshooting"),
        _bullet("No notifications? Run as admin (start.bat), allow privacy access, watcher open."),
        _bullet("Watcher syntax error? Use watcher not listen; run config to check paths."),
        _bullet("Wrong contact tag? Edit match[] in contacts.jsonl, then sync."),
        _bullet("Images missing? Check Phone Link photo folders in config; see intake / auto."),
        _bullet("Change a setting? config edit <key> <value> — config list for all keys."),
        _bullet("Still stuck? config — status view: folders, harvest, intake URL."),
        _bullet(
            "AI cannot see attachments? config — analyze should not be off; after a new "
            "image, read data/.analyze/latest.png (expires after analyze.ttl)."
        ),
    ]
    return "\n".join(lines)


def _footer() -> str:
    return "\n".join(
        [
            f"{MARGIN}{chalk.muted('Type')} {chalk.command('help')} {chalk.muted('for commands or')} "
            f"{chalk.command('how watcher')} {chalk.muted('for topic help.')}",
            "",
        ]
    )


def _topic_help_footer() -> str:
    return "\n".join(
        [
            "",
            f"{MARGIN}{chalk.muted('All commands:')} {chalk.command('help')}"
            f"{chalk.muted('  ·  Full guide:')} {chalk.command('how')}",
            "",
        ]
    )


# Longest keys first so "config list" matches before "config".
_HELP_TOPIC_RENDERERS: list[tuple[str, Callable[[], str]]] = [
    ("config list", _section_help_config_list),
    ("config edit", _section_help_config_edit),
    ("config get", _section_help_config_get),
    ("config reset", _section_help_config_reset),
    ("config", _section_config),
    ("watcher stop", _section_help_watcher_stop),
    ("watcher", _section_help_watcher),
    ("intake global", _section_help_intake_global),
    ("intake stop", _section_help_intake_stop),
    ("intake", _section_help_intake),
    ("outtake", _section_help_outtake),
    ("caught", _section_help_caught),
    ("contacts", _section_contacts),
    ("send", _section_send_shortcuts),
    ("sync", _section_help_sync),
    ("wipe", _section_help_wipe),
    ("status", _section_help_status),
    ("analyze", _section_help_analyze),
    ("calendar", _section_help_calendar),
    ("missed", _section_help_calls),
    ("calls", _section_help_calls),
    ("convo", _section_help_convo),
    ("ars", _section_help_ars),
]

_HELP_TOPIC_ALIASES: dict[str, str] = {
    "listen": "watcher",
    "listen stop": "watcher stop",
    "listen-stop": "watcher stop",
    "watcher-stop": "watcher stop",
    "doctor": "config",
    "check": "config",
    "tasks": "caught",
    "msg": "send",
    "text": "send",
    "sms": "send",
    "ls": "config list",
    "clear-data": "wipe",
    "factory-reset": "config reset",
    "auto-reply": "ars",
    "autoreply": "ars",
}


def help_topic_names() -> list[str]:
    return [key for key, _ in _HELP_TOPIC_RENDERERS]


def resolve_help_topic(parts: list[str]) -> str | None:
    """Normalize help args to a topic key, or None if unknown."""
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() in ("topics", "list", "all"):
        return "__topics__"
    query = " ".join(parts).lower().strip()
    query = _HELP_TOPIC_ALIASES.get(query, query)
    for key, _ in _HELP_TOPIC_RENDERERS:
        if query == key:
            return key
    return None


def render_help_topics_index() -> str:
    table = Table(
        head=["help topic", "about"],
        col_widths=[22, 40],
        value_cols=[1],
    )
    blurbs = {
        "watcher": "live notification capture",
        "watcher stop": "close watcher window",
        "caught": "browse captured messages",
        "contacts": "people and match rules",
        "send": "@tags and SMS compose",
        "config": "edit config.yaml from shell",
        "config edit": "set a config value",
        "config get": "read one setting",
        "config list": "all keys and values",
        "config reset": "restore config.example.yaml",
        "intake": "LAN upload to PC",
        "intake global": "public intake URL",
        "intake stop": "stop intake server",
        "outtake": "share link/file to phone",
        "sync": "Phone Link + contacts re-sync (auto 15m)",
        "wipe": "clear local data files",
        "status": "quick summary",
        "analyze": "AI snapshot folder (.analyze)",
        "calendar": "schedule SMS + optional Google sync",
        "calls": "Phone Link call log (1d)",
        "missed": "missed calls table",
        "convo": "SMS thread from Phone Link phone.db",
        "ars": "auto-reply session for agents",
    }
    for key in help_topic_names():
        table.push([key, blurbs.get(key, "")])
    lines = [
        _heading("Help topics"),
        _plain("Type how or help followed by a topic for detailed how-to on that command."),
        "",
        _indent_block(table.to_string()),
        "",
        _plain("Examples: how watcher  ·  help intake  ·  help sync  ·  how config list"),
    ]
    return "\n".join(lines)


def render_help_topic(parts: list[str]) -> str | None:
    """Topic-specific help for help <topic> — None if unknown."""
    key = resolve_help_topic(parts)
    if key is None:
        return None
    if key == "__topics__":
        return render_help_topics_index()
    for topic_key, renderer in _HELP_TOPIC_RENDERERS:
        if topic_key == key:
            return renderer() + _topic_help_footer()
    return None


def display_help_topic(parts: list[str]) -> None:
    """Print topic help (used from root shell and sub-screens)."""
    text = render_help_topic(parts)
    if not text:
        from telelink import pretty

        query = " ".join(parts)
        pretty.warn(f"no help topic: {query!r}")
        text = render_help_topics_index()
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(__import__("sys").stdout, "encoding", None) or "utf-8"
        print(chalk.strip(text).encode(enc, errors="replace").decode(enc), flush=True)


def render_how_guide() -> str:
    """Full TeleLink how-to guide for terminal display."""
    sections = [
        _hero(),
        _section_overview(),
        _section_quick_start(),
        _section_daily(),
        _section_commands(),
        _section_send_shortcuts(),
        _section_help_ars(),
        _section_config(),
        _section_contacts(),
        _section_help_sync(),
        _section_data(),
        _section_analyze(),
        _section_intake_outtake(),
        _section_keys(),
        _section_troubleshoot(),
        _footer(),
    ]
    return "\n".join(s for s in sections if s)
