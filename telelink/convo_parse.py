"""Parse convo shell/CLI arguments — scope, limit, target contact."""

from __future__ import annotations

import re
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from telelink.calendar_time import owner_timezone
from telelink.duration import parse_duration

_SCOPE_WORDS = frozenset(
    {
        "all",
        "today",
        "yesterday",
        "week",
        "thisweek",
        "this-week",
    }
)

_INCOMING_WORDS = frozenset(
    {
        "incoming",
        "received",
        "from",
        "they",
        "them",
        "their",
    }
)

_CLI_FLAG_TOKENS = frozenset({"--raw", "-raw", "--json", "-json"})

_LAST_RE = re.compile(r"^last(\d+)$", re.IGNORECASE)


@dataclass
class ConvoQuery:
    target: str = ""
    limit: int | None = None
    show_all: bool = False
    since: datetime | None = None
    until: datetime | None = None
    json: bool = False
    raw: bool = False
    threads: bool = False
    incoming_only: bool = False


def strip_cli_flags(tokens: list[str]) -> tuple[list[str], bool, bool]:
    """Remove --raw/--json mistakenly captured in REMAINDER (e.g. convo mom --raw)."""
    rest: list[str] = []
    raw = False
    json_mode = False
    for t in tokens:
        low = t.lower()
        if low in _CLI_FLAG_TOKENS:
            if low in ("--raw", "-raw"):
                raw = True
            else:
                json_mode = True
            continue
        rest.append(t)
    return rest, raw, json_mode


def _start_of_day(config: dict[str, Any] | None, *, offset_days: int = 0) -> datetime:
    tz = owner_timezone(config)
    now = datetime.now(timezone.utc).astimezone(tz)
    day = (now + timedelta(days=offset_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day.astimezone(timezone.utc)


def _apply_scope_word(word: str, query: ConvoQuery, *, config: dict[str, Any] | None) -> bool:
    w = word.lower()
    if w == "all":
        query.show_all = True
        query.limit = None
        return True
    if w == "today":
        query.since = _start_of_day(config, offset_days=0)
        return True
    if w == "yesterday":
        query.since = _start_of_day(config, offset_days=-1)
        query.until = _start_of_day(config, offset_days=0)
        return True
    if w in ("week", "thisweek", "this-week"):
        query.since = datetime.now(timezone.utc) - timedelta(days=7)
        return True
    from telelink.contacts import looks_like_phone

    if looks_like_phone(w):
        return False
    secs = parse_duration(w)
    if secs and not w.isdigit():
        query.since = datetime.now(timezone.utc) - timedelta(seconds=secs)
        return True
    return False


def parse_convo_tokens(tokens: list[str], *, config: dict[str, Any] | None = None) -> ConvoQuery:
    """Parse tokens after 'convo' into a ConvoQuery."""
    query = ConvoQuery()
    if not tokens:
        raise ValueError(
            "usage: convo <contact|+number>  ·  convo last 5 mom  ·  convo today mom  ·  convo all mom"
        )

    if tokens[0].lower() == "threads":
        query.threads = True
        return query

    remaining: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.lower()

        if low == "json":
            query.json = True
            i += 1
            continue
        if low == "raw":
            query.raw = True
            i += 1
            continue
        if low in _INCOMING_WORDS:
            query.incoming_only = True
            i += 1
            continue
        if low == "last" and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            query.limit = int(tokens[i + 1])
            i += 2
            continue
        m_last = _LAST_RE.match(t)
        if m_last:
            query.limit = int(m_last.group(1))
            i += 1
            continue
        if _apply_scope_word(low, query, config=config):
            i += 1
            continue
        remaining.append(t)
        i += 1

    if not remaining:
        if query.threads:
            return query
        raise ValueError(
            "missing contact or phone — e.g. convo mom  ·  convo +15559876543  ·  convo last 10 mom"
        )

    query.target = " ".join(remaining).strip().strip('"').strip("'")
    if not query.target:
        raise ValueError("missing contact or phone number")

    if query.show_all:
        query.limit = None
    elif query.limit is None and query.since is None:
        query.limit = int((config or {}).get("convo", {}).get("default_limit") or 50)

    return query


def parse_convo_line(line: str, *, config: dict[str, Any] | None = None) -> ConvoQuery:
    import shlex

    text = (line or "").strip()
    if text.lower().startswith("convo "):
        text = text[6:].strip()
    parts = shlex.split(text, posix=False) if text else []
    return parse_convo_tokens(parts, config=config)


def convo_query_to_namespace(query: ConvoQuery) -> Namespace:
    return Namespace(
        target=query.target,
        limit=query.limit,
        show_all=query.show_all,
        since=query.since,
        until=query.until,
        json=query.json,
        raw=query.raw,
        threads=query.threads,
        incoming_only=query.incoming_only,
    )
