"""CLI tables inspired by Automattic/cli-table (https://github.com/Automattic/cli-table)."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from telelink import chalk
from telelink.terminal import terminal_width

_CELL_PAD = 2  # one space on each side of cell content


@dataclass(frozen=True)
class TableChars:
    top: str
    top_mid: str
    top_left: str
    top_right: str
    bottom: str
    bottom_mid: str
    bottom_left: str
    bottom_right: str
    left: str
    left_mid: str
    mid: str
    mid_mid: str
    right: str
    right_mid: str
    middle: str


_UNICODE = TableChars(
    top="─",
    top_mid="┬",
    top_left="┌",
    top_right="┐",
    bottom="─",
    bottom_mid="┴",
    bottom_left="└",
    bottom_right="┘",
    left="│",
    left_mid="├",
    mid="─",
    mid_mid="┼",
    right="│",
    right_mid="┤",
    middle="│",
)

_ASCII = TableChars(
    top="-",
    top_mid="+",
    top_left="+",
    top_right="+",
    bottom="-",
    bottom_mid="+",
    bottom_left="+",
    bottom_right="+",
    left="|",
    left_mid="+",
    mid="-",
    mid_mid="+",
    right="|",
    right_mid="+",
    middle="|",
)


def unicode_terminal() -> bool:
    from telelink.terminal import unicode_capable

    return unicode_capable()


def _chars() -> TableChars:
    return _UNICODE if unicode_terminal() else _ASCII


def _visible(text: str) -> str:
    return chalk.strip(text)


def _visible_len(text: str) -> int:
    return len(_visible(text))


class Table:
    """Horizontal table (cli-table style)."""

    def __init__(
        self,
        head: Sequence[str] | None = None,
        *,
        aligns: Sequence[str] | None = None,
        col_widths: Sequence[int] | None = None,
        max_width: int | None = None,
        value_cols: Sequence[int] | None = None,
    ) -> None:
        self.head = [str(h) for h in (head or [])]
        self.rows: list[list[str]] = []
        self.aligns = list(aligns or [])
        self.col_widths = list(col_widths or [])
        self.max_width = max_width
        self.value_cols = set(value_cols or [])

    def push(self, row: Sequence[Any]) -> None:
        self.rows.append([str(c) for c in row])

    def _widths(self) -> list[int]:
        cols = max(len(self.head), max((len(r) for r in self.rows), default=0))
        widths = [0] * cols
        if self.col_widths:
            for i, w in enumerate(self.col_widths):
                if i < cols:
                    widths[i] = w
        for i, cell in enumerate(self.head):
            widths[i] = max(widths[i], _visible_len(cell))
        for row in self.rows:
            for i, cell in enumerate(row):
                if i < cols:
                    widths[i] = max(widths[i], _visible_len(cell))

        limit = self.max_width or terminal_width()
        frame = cols + 1 + sum(2 for _ in range(cols))  # bars + cell padding
        budget = max(20, limit - frame)
        total = sum(widths)
        if total > budget and cols:
            # Shrink the widest columns first (usually descriptions).
            order = sorted(range(cols), key=lambda i: widths[i], reverse=True)
            over = total - budget
            for idx in order:
                if over <= 0:
                    break
                room = max(0, widths[idx] - 4)
                cut = min(room, over)
                widths[idx] -= cut
                over -= cut
        return widths

    def _border_segments(self, widths: list[int]) -> list[int]:
        return [w + _CELL_PAD for w in widths]

    def _hline(self, left: str, join: str, right: str, fill: str, widths: list[int]) -> str:
        segments = self._border_segments(widths)
        body = join.join(fill * seg for seg in segments)
        return chalk.muted(left + body + right)

    def _align(self, text: str, width: int, idx: int) -> str:
        align = "left"
        if idx < len(self.aligns):
            align = self.aligns[idx]
        plain = _visible(text)
        if _visible_len(plain) > width:
            plain = plain[: max(1, width - 3)] + "..."
        if align == "right":
            return plain.rjust(width)
        if align == "center":
            return plain.center(width)
        return plain.ljust(width)

    def _style_cell(self, text: str, *, header: bool = False, value_col: bool = False) -> str:
        if header:
            return chalk.label(text)
        if value_col:
            return chalk.plain(text)
        return chalk.baby(text)

    def _row(self, cells: list[str], widths: list[int], *, header: bool = False) -> str:
        c = _chars()
        parts: list[str] = []
        for i, w in enumerate(widths):
            cell = cells[i] if i < len(cells) else ""
            raw = self._align(cell, w, i)
            value_col = (not header and i in self.value_cols) or (not header and i > 0 and not self.value_cols)
            styled = self._style_cell(raw, header=header, value_col=value_col)
            parts.append(f" {styled} ")
        inner = ""
        for i, part in enumerate(parts):
            if i:
                inner += chalk.muted(c.middle)
            inner += part
        return chalk.muted(c.left) + inner + chalk.muted(c.right)

    def to_string(self) -> str:
        if not self.head and not self.rows:
            return ""
        c = _chars()
        widths = self._widths()
        lines: list[str] = []
        if self.head:
            lines.append(self._hline(c.top_left, c.top_mid, c.top_right, c.top, widths))
            lines.append(self._row(self.head, widths, header=True))
        if self.head and self.rows:
            lines.append(self._hline(c.left_mid, c.mid_mid, c.right_mid, c.mid, widths))
        for i, row in enumerate(self.rows):
            lines.append(self._row(row, widths))
            if i < len(self.rows) - 1 and not self.head:
                lines.append(self._hline(c.left_mid, c.mid_mid, c.right_mid, c.mid, widths))
        if self.head or self.rows:
            lines.append(self._hline(c.bottom_left, c.bottom_mid, c.bottom_right, c.bottom, widths))
        return "\n".join(lines)


def _short_ts(value: str) -> str:
    if not value:
        return ""
    if "T" in value:
        date, clock = value.split("T", 1)
        clock = clock.replace("Z", "")[:8]
        return f"{date} {clock}"
    return value[:19]


def _short_task(value: str, limit: int = 46) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def caught_table(rows: Iterable[dict[str, Any]], *, title: str | None = None) -> str:
    table = Table(
        head=["Contact", "Platform", "Kind", "Sender", "Message", "Files", "Time"],
        aligns=["left", "left", "left", "left", "left", "right", "left"],
        col_widths=[10, 10, 6, 14, 28, 5, 16],
        value_cols=[1, 2, 3, 4, 5, 6],
    )
    for row in rows:
        att = len(row.get("attachments") or [])
        table.push(
            [
                row.get("contact") or row.get("client") or "-",
                row.get("channel") or "?",
                row.get("message_kind") or "text",
                _short_task(row.get("sender") or row.get("sender_id") or "?", 14),
                _short_task(row.get("task") or "", 28),
                str(att) if att else "-",
                _short_ts(str(row.get("timestamp") or "")),
            ]
        )
    body = table.to_string()
    if not body:
        return "(nothing caught yet)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


tasks_table = caught_table


def calls_table(rows: Iterable[dict[str, Any]], *, title: str | None = None) -> str:
    table = Table(
        head=["Contact", "Caller", "Kind", "When", "Detail"],
        aligns=["left", "left", "left", "left", "left"],
        col_widths=[12, 14, 10, 16, 24],
        value_cols=[1, 2, 3, 4],
    )
    for row in rows:
        table.push(
            [
                row.get("contact") or "-",
                _short_task(row.get("caller") or row.get("sender_id") or "?", 14),
                row.get("kind") or "?",
                _short_ts(str(row.get("timestamp") or "")),
                _short_task(row.get("body") or "", 24),
            ]
        )
    body = table.to_string()
    if not body:
        return "(no calls logged)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def convo_table(
    rows: Iterable[dict[str, Any]],
    *,
    title: str | None = None,
    config: dict[str, Any] | None = None,
    json_view: bool = False,
) -> str:
    from telelink.calendar_time import format_local_short

    items = list(rows)
    # Oldest at top (chat order)
    items.sort(key=lambda r: r.get("timestamp") or "")

    if json_view:
        table = Table(
            head=["When", "Dir", "Message", "Source"],
            aligns=["left", "left", "left", "left"],
            col_widths=[18, 4, 40, 12],
            value_cols=[0, 2, 3],
        )
        for row in items:
            ts = str(row.get("timestamp") or "")
            try:
                when = format_local_short(
                    datetime.fromisoformat(ts.replace("Z", "+00:00")),
                    config=config,
                )
            except (TypeError, ValueError):
                when = _short_ts(ts)
            table.push(
                [
                    when,
                    row.get("direction") or "?",
                    _short_task(row.get("body") or "", 40),
                    row.get("source") or "-",
                ]
            )
    else:
        table = Table(
            head=["When", " ", "Message"],
            aligns=["left", "left", "left"],
            col_widths=[18, 3, 52],
            value_cols=[0, 2],
        )
        for row in items:
            ts = str(row.get("timestamp") or "")
            try:
                when = format_local_short(
                    datetime.fromisoformat(ts.replace("Z", "+00:00")),
                    config=config,
                )
            except (TypeError, ValueError):
                when = _short_ts(ts)
            direction = row.get("direction") or "?"
            arrow = chalk.muted("←") if direction == "in" else chalk.value("→")
            table.push([when, arrow, _short_task(row.get("body") or "", 52)])

    body = table.to_string()
    if not body:
        return "(no messages)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def convo_threads_table(rows: Iterable[dict[str, Any]], *, title: str | None = None) -> str:
    table = Table(
        head=["Name", "Number", "Messages", "Last"],
        aligns=["left", "left", "left", "left"],
        col_widths=[16, 16, 8, 18],
        value_cols=[0, 1, 2, 3],
    )
    for row in rows:
        name = row.get("peer_name") or row.get("peer") or "-"
        number = row.get("phone") or row.get("peer") or "-"
        table.push(
            [
                _short_task(str(name), 16),
                _short_task(str(number), 16),
                str(row.get("msg_count") or "-"),
                _short_ts(str(row.get("timestamp") or "")),
            ]
        )
    body = table.to_string()
    if not body:
        return "(no threads)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def contacts_table(rows: Iterable[dict[str, Any]], *, title: str | None = None) -> str:
    from telelink.contacts import dial_phone

    table = Table(
        head=["Name", "Phone", "Platform", "Match", "Managed"],
        aligns=["left", "left", "left", "left", "left"],
        col_widths=[14, 14, 10, 18, 8],
        value_cols=[1, 2, 3, 4],
    )
    for row in rows:
        match = row.get("match") or []
        match_s = ", ".join(str(m) for m in match[:4])
        if len(match) > 4:
            match_s += "…"
        number = dial_phone(row) or "-"
        managed = "yes" if row.get("managed", True) else "no"
        table.push(
            [
                row.get("name") or "-",
                number,
                row.get("platform") or "-",
                match_s or "-",
                managed,
            ]
        )
    body = table.to_string()
    if not body:
        return "(no contacts)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def full_records_table(rows: Iterable[dict[str, Any]], *, title: str | None = None) -> str:
    items = list(rows)
    if not items:
        return "(nothing caught yet)"
    keys: list[str] = []
    for row in items:
        for key in row:
            if key not in keys:
                keys.append(key)
    table = Table(head=keys[:10], value_cols=list(range(1, 10)))
    for row in items:
        table.push([_cell(row.get(k)) for k in keys[:10]])
    body = table.to_string()
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def json_table(data: Any, *, title: str | None = None) -> str:
    """Render JSON list/dict data as a readable table."""
    if isinstance(data, list):
        if not data:
            return "(empty)"
        if all(isinstance(item, dict) for item in data):
            if _looks_like_task(data[0]):
                return caught_table(data, title=title)
            return _dicts_table(data, title=title)
        return _values_table(data, title=title)
    if isinstance(data, dict):
        if all(isinstance(v, list) and v and isinstance(v[0], dict) for v in data.values()):
            parts = []
            for key in sorted(data):
                items = data[key]
                parts.append(caught_table(items, title=f"{key} ({len(items)})"))
            return "\n\n".join(parts)
        return _mapping_table(data, title=title)
    return str(data)


def _looks_like_task(row: dict[str, Any]) -> bool:
    return "task" in row and ("channel" in row or "timestamp" in row)


def _dicts_table(rows: list[dict[str, Any]], *, title: str | None = None) -> str:
    keys = list(rows[0].keys())
    for row in rows[1:]:
        for key in row:
            if key not in keys:
                keys.append(key)
    head = keys[:8]
    table = Table(head=head, value_cols=list(range(1, len(head))))
    for row in rows:
        table.push([_cell(row.get(k)) for k in head])
    body = table.to_string()
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def _mapping_table(data: dict[str, Any], *, title: str | None = None) -> str:
    table = Table(head=["Key", "Value"], col_widths=[16, 48], value_cols=[1])
    for key in sorted(data):
        table.push([str(key), _cell(data[key])])
    body = table.to_string()
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def _values_table(values: list[Any], *, title: str | None = None) -> str:
    table = Table(head=["#", "Value"], col_widths=[4, 52], value_cols=[1])
    for i, value in enumerate(values, 1):
        table.push([str(i), _cell(value)])
    body = table.to_string()
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
        return _short_task(text, 60)
    return _short_task(str(value), 60)


def _section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"{chalk.label(title)}\n{body}"


def help_table() -> str:
    commands = Table(
        head=["Command", "Description"],
        col_widths=[10, 52],
        value_cols=[1],
    )
    for cmd, desc in _HELP_COMMANDS:
        commands.push([cmd, desc])

    nav = Table(
        head=["Key", "Description"],
        col_widths=[14, 48],
        value_cols=[1],
    )
    for cmd, desc in _NAV_COMMANDS:
        nav.push([cmd, desc])

    examples = Table(
        head=["Example", "Notes"],
        col_widths=[22, 40],
        value_cols=[1],
    )
    for ex, note in _HELP_EXAMPLES:
        examples.push([ex, note])

    tips = textwrap.indent(
        "\n".join(chalk.plain(line) for line in _HELP_TIPS),
        "  ",
    )
    blocks = [
        _section("commands", commands.to_string()),
        _section("navigation", nav.to_string()),
        _section("examples", examples.to_string()),
        f"{chalk.label('tips')}\n{tips}",
    ]
    return "\n\n".join(block for block in blocks if block)


def calendar_table(
    rows: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    title: str | None = None,
) -> str:
    from telelink.calendar_time import format_local_short, format_relative_until

    table = Table(
        head=["Name", "To", "Fires", "In", "Status", "Message"],
        aligns=["left", "left", "left", "left", "left", "left"],
        col_widths=[12, 10, 18, 10, 8, 24],
        value_cols=[1, 2, 3, 4, 5],
    )
    for row in rows:
        fire = row.get("fire_at") or ""
        rel = ""
        local = fire[:16]
        try:
            dt = datetime.fromisoformat(fire.replace("Z", "+00:00"))
            rel = format_relative_until(dt)
            local = format_local_short(dt, config=config)
        except (TypeError, ValueError):
            pass
        to_cell = row.get("to") or "-"
        for part in (row.get("notes") or "").split(" · "):
            if part.startswith("contact:"):
                to_cell = f"{part.split(':', 1)[1]} ({to_cell})"
                break
        table.push(
            [
                row.get("name") or "-",
                to_cell,
                local,
                rel or "-",
                row.get("status") or "pending",
                _short_task(row.get("body") or "", 24),
            ]
        )
    body = table.to_string()
    if not body:
        return "(no scheduled events)"
    if title:
        return f"{chalk.label(title)}\n{body}"
    return body


def calendar_status_table(
    config: dict[str, Any],
    *,
    pending: int,
    due: int,
) -> str:
    from telelink.calendar_google import google_status

    cal = config.get("calendar") or {}
    g = google_status(config)
    table = Table(
        head=["Field", "Value"],
        col_widths=[14, 48],
        value_cols=[1],
    )
    table.push(["enabled", "yes" if cal.get("enabled", True) else "no"])
    table.push(["pending", str(pending)])
    table.push(["due now", str(due)])
    table.push(["poll", f"{cal.get('poll_seconds', 30)}s"])
    table.push(["remind", str(cal.get("remind_interval", "15m"))])
    table.push(["google", "on" if g["enabled"] else "off"])
    if g["enabled"]:
        if not g["library"]:
            table.push(["google libs", g["library_note"] or "missing — pip install google-api-python-client google-auth-oauthlib"])
        table.push(["google creds", g["credentials"] or "(missing)"])
        table.push(["google token", "saved" if g["token_saved"] else "not connected — calendar connect google"])
        table.push(["google calendar", g["calendar_id"]])
        table.push(["last sync", g["last_sync"]])
    return table.to_string()


def calendar_event_status_table(event: dict[str, Any], *, config: dict[str, Any] | None = None) -> str:
    from telelink.calendar_time import format_local_short, format_relative_until

    fire = event.get("fire_at") or ""
    rel = ""
    local = fire
    try:
        dt = datetime.fromisoformat(fire.replace("Z", "+00:00"))
        rel = format_relative_until(dt)
        local = format_local_short(dt, config=config)
    except (TypeError, ValueError):
        pass
    table = Table(
        head=["Field", "Value"],
        col_widths=[14, 48],
        value_cols=[1],
    )
    for key, val in [
        ("name", event.get("name")),
        ("status", event.get("status")),
        ("kind", event.get("kind")),
        ("to", event.get("to")),
        ("fires", local),
        ("countdown", rel),
        ("source", event.get("source")),
        ("google id", event.get("google_event_id") or "-"),
        ("error", event.get("error") or "-"),
    ]:
        table.push([str(key), _short_task(str(val or ""), 48)])
    if event.get("body"):
        table.push(["message", _short_task(event["body"], 48)])
    return f"{chalk.label(event.get('name') or 'event')}\n{table.to_string()}"


def status_table(
    *,
    total: int,
    matched: int,
    channels: dict[str, int],
    caught_file: str,
    attachments_dir: str,
    tasks_file: str | None = None,
) -> str:
    table = Table(
        head=["Field", "Value"],
        col_widths=[12, 52],
        value_cols=[1],
    )
    table.push(["caught", f"{total} notifications, {matched} matched contacts"])
    if channels:
        parts = ", ".join(f"{k} {v}" for k, v in sorted(channels.items(), key=lambda x: -x[1]))
        table.push(["channels", parts])
    table.push(["output", str(caught_file or tasks_file or "")])
    table.push(["attachments", str(attachments_dir)])
    return table.to_string()


_HELP_COMMANDS = [
    ("watcher", "start watcher in new window"),
    ("watcher stop", "force stop watcher window"),
    ("caught", "notifications viewer (table / json / gron)"),
    ("contacts", "contacts table + sync"),
    ("sync", "re-sync Phone Link + contacts from all sources"),
    ("sync --caught", "re-sync + import phone senders from caught log"),
    ("help sync", "Phone Link re-sync, stale cache, auto-sync config"),
    ("send <who> <msg>", "SMS now via Phone Link"),
    ("send in1m <who> <msg>", "schedule SMS (in1m, in%2hour%, in%30m%, …)"),
    ("intake", "LAN server — QR or SMS the link"),
    ("intake global", "public URL (tunnel + pyhttpd server)"),
    ("intake stop", "stop intake server"),
    ("outtake <url|file…>", "QR — link or GitHub share (multiple files → zip)"),
    ("auto", "auto image intake guide"),
    ("config", "status — paths, folders, intake URL"),
    ("config edit <key> <val>", "set config.yaml (auto-save)"),
    ("config get <key>", "print one setting"),
    ("config list", "all config keys and values"),
    ("config reset", "restore config.yaml from config.example.yaml"),
    ("how", "full how-to guide"),
    ("how <topic>", "topic guide (e.g. how watcher)"),
    ("calendar", "scheduled SMS events table"),
    ("calendar add <name> …", "schedule a message for later"),
    ("calendar status", "calendar + Google sync health"),
    ("calls", "recent Phone Link calls (1d log)"),
    ("missed", "missed calls table"),
    ("convo <who>", "SMS thread from Phone Link phone.db"),
    ("convo last 5 mom", "last 5 messages with contact"),
    ("convo today mom", "today's messages · convo all mom"),
    ("convo threads", "list recent Phone Link threads"),
    ("status", "quick summary"),
    ("wipe <target>", "clear local data (caught, sent, contacts, all, …)"),
    ("wipe all --yes", "wipe everything without prompt"),
    ("clear / cc", "clear screen"),
    ("help", "command list (this screen)"),
    ("help <topic>", "topic guide (e.g. help watcher)"),
    ("help topics", "list all help topics"),
    ("exit", "quit"),
]

_NAV_COMMANDS = [
    ("ctrl+h", "help"),
    ("ctrl+b", "go back one screen"),
    ("ctrl+c", "cancel flow · exit"),
]

_HELP_EXAMPLES = [
    ("caught contacts", "matched contacts only"),
    ("caught group channel", "group by platform/channel"),
    ("caught last 5", "five most recent notifications"),
    ("caught json", "all JSON fields in a table"),
    ("caught gron", "greppable output"),
    ("contacts sync", "import phones from config.yaml"),
    ("sync", "re-sync Phone Link contacts + clear stale caches"),
    ("sync --caught", "re-sync + import phone senders from caught"),
    ("config edit auto_sync false", "disable background auto-sync"),
    ("config edit sync_interval 1h", "change auto-sync interval"),
    ("config edit business Your Business", "set business name in config.yaml"),
    ("config edit port 9000", "change intake port"),
    ("config list", "browse every config key"),
    ("send Shawk On my way", "text by contact name"),
    ("send in1m myself test", "schedule in 1 minute — no % needed"),
    ("send in20s myself ping", "schedule in 20 seconds"),
    ('send in%2hour% girlfriend Hey bro', "schedule — does not send until due"),
    ('send in%2pm today% "Mom" Running late', "quote multi-word time or names"),
    ('calendar add love girlfriend "in 3h" "I love you!"', "schedule SMS for 3 hours from now"),
    ("calendar delay love 2pm tomorrow", "postpone an event"),
    ("send +15551234567 Hello", "text by phone number"),
    ('send +1… Hi from @nameshort at @business', "owner tags from config.yaml"),
    ("send +1… line1 /n line2", "/n becomes a newline in the message"),
    ("missed", "table of missed calls"),
    ("calls", "table of recent calls"),
    ("convo mom", "message history with Mom (Phone Link DB)"),
    ("convo +15559876543", "thread by phone number"),
    ("convo last 10 girlfriend", "last 10 texts"),
    ("convo today mom", "today only"),
    ("convo threads", "recent conversations in phone.db"),
    ("wipe caught", "empty caught.jsonl"),
    ("wipe calls", "empty calls.jsonl"),
    ("wipe all --yes", "reset all data/ files (keeps config.yaml)"),
]

_HELP_TIPS = [
    "how <topic> or help <topic> — topic guide: how watcher, help sync, help intake, …",
    "sync: re-reads Phone Link contacts.db; startup sync + auto every 15m while shell is open (config edit sync_interval 30m).",
    "owner: in config.yaml is you (Your Business) — not a contact.",
    "send messages: @nameshort @business @email @namefull @tone — values from owner: block.",
    "send messages: /n inserts a newline (spaces around /n are trimmed).",
    "contacts: edit data/contacts.jsonl — match rules tag notifications.",
    "routing.only_contacts: true skips unmatched notifications.",
]
