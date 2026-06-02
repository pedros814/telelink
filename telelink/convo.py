"""CLI — convo command (Phone Link message history)."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import datetime, timezone
from typing import Any

from telelink import pretty
from telelink.convo_parse import ConvoQuery, parse_convo_tokens, strip_cli_flags
from telelink.ora import ora
from telelink.session import get_session
from telelink.table import convo_table


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    since: datetime | None,
    until: datetime | None,
    limit: int | None,
    incoming_only: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if incoming_only:
        from telelink.received import is_incoming_row
    for row in rows:
        if incoming_only and not is_incoming_row(row):
            continue
        ts = _parse_ts(str(row.get("timestamp") or ""))
        if since and ts and ts < since:
            continue
        if until and ts and ts >= until:
            continue
        out.append(row)
    out.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    if limit is not None:
        return out[: max(1, limit)]
    return out


def _read_sent_fallback(
    config: dict[str, Any],
    *,
    phone: str,
    display: str,
    limit: int,
) -> list[dict[str, Any]]:
    from telelink.contacts import dial_digits
    from telelink.sent_log import _read_lines, sent_log_path

    path = sent_log_path(config)
    dial = dial_digits(phone)
    rows: list[dict[str, Any]] = []
    for line in _read_lines(path):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        to_dial = dial_digits(str(rec.get("to_phone") or rec.get("dial") or ""))
        if dial and to_dial and dial != to_dial:
            continue
        body = str(rec.get("body") or "").strip()
        if not body:
            continue
        rows.append(
            {
                "id": f"sent-{rec.get('timestamp', len(rows))}",
                "direction": "out",
                "body": body,
                "from_address": "",
                "to_address": phone,
                "peer": phone,
                "peer_name": display,
                "timestamp": str(rec.get("timestamp") or ""),
                "source": "sent.jsonl",
            }
        )
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return rows[:limit]


def _read_caught_fallback(
    config: dict[str, Any],
    *,
    phone: str,
    display: str,
    contact_store: Any,
    limit: int,
) -> list[dict[str, Any]]:
    from telelink.classify import classify_channel, normalize_sender_id, resolve_contact
    from telelink.contacts import dial_digits

    store = get_session().caught_store
    dial = dial_digits(phone)
    rows: list[dict[str, Any]] = []
    for row in store.list_caught():
        ch = (row.get("channel") or "").lower()
        if ch not in ("sms", "imessage", "messages", "text"):
            continue
        sender = str(row.get("sender") or row.get("sender_id") or "")
        sid = normalize_sender_id(sender)
        if dial and dial not in sid and sid not in dial:
            contact_name = str(row.get("contact") or "")
            if display.lower() not in contact_name.lower() and contact_name.lower() not in display.lower():
                _, matched = resolve_contact(config, sender, row.get("raw_message") or "", store=contact_store)
                if not matched or contact_name.lower() != display.lower():
                    continue
        body = str(row.get("raw_message") or row.get("task") or "").strip()
        if not body:
            continue
        rows.append(
            {
                "id": f"caught-{row.get('id', len(rows))}",
                "direction": "in",
                "body": body,
                "from_address": sender,
                "to_address": "",
                "peer": sender,
                "peer_name": display,
                "timestamp": str(row.get("timestamp") or ""),
                "source": "caught.jsonl",
            }
        )
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return rows[:limit]


def fetch_conversation(
    query: ConvoQuery,
    *,
    config: dict[str, Any],
    contact_store: Any,
) -> tuple[list[dict[str, Any]], str, str, str]:
    """
    Load messages for query. Returns (rows, display, phone, source_note).
    """
    from telelink.phone_link_messages import (
        phone_keys_for_target,
        read_conversation_messages,
        resolve_phone_db_path,
    )

    if query.threads:
        db = resolve_phone_db_path(config)
        if not db:
            return [], "", "", "no phone.db"
        from telelink.phone_link_messages import list_conversation_threads

        threads = list_conversation_threads(db, limit=query.limit or 40)
        return threads, "", "", f"phone.db ({db.name})"

    keys, display, phone = phone_keys_for_target(
        query.target, config=config, contact_store=contact_store
    )
    max_rows = 2000 if query.show_all else (query.limit or 50)
    if query.show_all:
        max_rows = int((config.get("convo") or {}).get("max_all") or 500)

    db = resolve_phone_db_path(config)
    rows: list[dict[str, Any]] = []
    source = ""
    if db:
        rows = read_conversation_messages(db, phone_keys=keys, limit=max_rows)
        source = f"phone.db ({db.name})"

    convo_cfg = config.get("convo") or {}
    ui_fallback = convo_cfg.get("ui_fallback", True) is not False
    if not rows and ui_fallback:
        from telelink.phone_link_convo_ui import read_conversation_from_ui

        ui_rows, ui_note = read_conversation_from_ui(
            display=display,
            phone=phone,
            phone_keys=keys,
            limit=max_rows if query.limit else max_rows,
            navigate=True,
            config=config,
            target=query.target,
        )
        if ui_rows:
            rows = ui_rows
            source = ui_note

    if not rows:
        fb_limit = max_rows
        rows = _read_sent_fallback(config, phone=phone, display=display, limit=fb_limit)
        if rows:
            source = "sent.jsonl (Phone Link DB empty — outbound only)"
        if not rows:
            rows = _read_caught_fallback(
                config,
                phone=phone,
                display=display,
                contact_store=contact_store,
                limit=fb_limit,
            )
            if rows:
                source = "caught.jsonl (notifications — not full thread history)"

    rows = _filter_rows(
        rows,
        since=query.since,
        until=query.until,
        limit=query.limit,
        incoming_only=query.incoming_only,
    )
    if not rows and not source:
        source = "no phone.db"
    return rows, display, phone, source


def _query_from_args(args: Namespace, *, config: dict[str, Any]) -> ConvoQuery:
    """Build ConvoQuery from CLI rest tokens or shell-parsed namespace fields."""
    rest = [str(x) for x in (getattr(args, "rest", None) or []) if str(x).strip()]
    if rest:
        rest, flag_raw, flag_json = strip_cli_flags(rest)
        query = parse_convo_tokens(rest, config=config)
        if flag_raw:
            query.raw = True
        if flag_json:
            query.json = True
        return query

    if getattr(args, "threads", False):
        return ConvoQuery(
            threads=True,
            limit=getattr(args, "limit", None),
            json=bool(getattr(args, "json", False)),
            raw=bool(getattr(args, "raw", False)),
        )

    target = str(getattr(args, "target", "") or "").strip()
    if not target:
        raise ValueError(
            "usage: convo <contact|+number>  ·  convo last 5 mom  ·  convo today mom  ·  convo all mom"
        )

    query = ConvoQuery(
        target=target,
        limit=getattr(args, "limit", None),
        show_all=bool(getattr(args, "show_all", False)),
        since=getattr(args, "since", None),
        until=getattr(args, "until", None),
        json=bool(getattr(args, "json", False)),
        raw=bool(getattr(args, "raw", False)),
    )
    if query.show_all:
        query.limit = None
    elif query.limit is None and query.since is None:
        query.limit = int((config or {}).get("convo", {}).get("default_limit") or 50)
    return query


def cmd_convo(args: Namespace) -> int:
    config = get_session().config_fresh()
    convo_cfg = config.get("convo") or {}
    if convo_cfg.get("enabled", True) is False:
        pretty.warn("convo is disabled — config edit convo_enabled true")
        return 1

    try:
        query = _query_from_args(args, config=config)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1
    if getattr(args, "json", False):
        query.json = True
    if getattr(args, "raw", False):
        query.raw = True

    with ora("Loading conversation", kind="load"):
        rows, display, phone, source = fetch_conversation(
            query,
            config=config,
            contact_store=get_session().contact_store,
        )

    if query.raw:
        from telelink.json_out import print_json

        for row in rows:
            print_json(row, indent=None)
        if not rows and not query.threads:
            from telelink.phone_link_messages import describe_phone_db_status

            status = describe_phone_db_status(config)
            if not status.get("found"):
                pretty.info(
                    "CONVO",
                    "phone.db not found — open Phone Link → Messages and sync a thread first",
                )
            else:
                pretty.info(
                    "CONVO",
                    "no messages — open Phone Link → Messages and let sync finish",
                )
        return 0

    if query.threads:
        from telelink.table import convo_threads_table

        pretty._print_line(convo_threads_table(rows, title="Recent threads (Phone Link)"))
        if not rows:
            pretty.info(
                "CONVO",
                "no threads in phone.db — open Phone Link Messages tab on this PC",
            )
        return 0

    title_parts = [display or query.target]
    if phone and display and phone not in display:
        title_parts.append(phone)
    title = " · ".join(title_parts)
    if query.limit:
        title = f"{title} (last {query.limit})"
    elif query.since:
        title = f"{title} (filtered)"
    if source:
        title = f"{title} — {source}"

    pretty._print_line(convo_table(rows, title=title, config=config, json_view=query.json))
    if not rows:
        from telelink.phone_link_messages import describe_phone_db_status

        status = describe_phone_db_status(config)
        if not status.get("found"):
            hint = (
                "Phone Link has not created phone.db (normal on iPhone) — keep Phone Link open "
                "on the Messages tab with this thread visible, then run convo again."
            )
            if status.get("expected_dir"):
                from pathlib import Path

                hint += f" Android may cache at {Path(status['expected_dir']) / 'phone.db'}"
            pretty.info("CONVO", hint)
        elif "sent.jsonl" in source or "caught.jsonl" in source:
            pretty.info(
                "CONVO",
                "no messages in phone.db for this contact — showing partial history from "
                + ("sent.jsonl" if "sent.jsonl" in source else "caught.jsonl"),
            )
        else:
            pretty.info(
                "CONVO",
                "no messages for this contact in phone.db — open that thread in "
                "Phone Link → Messages and try again",
            )
    return 0


def dispatch_convo_command(rest: list[str]) -> int:
    """Shell: convo …"""
    config = get_session().config_fresh()
    try:
        query = parse_convo_tokens(rest, config=config)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1
    from telelink.convo_parse import convo_query_to_namespace

    return cmd_convo(convo_query_to_namespace(query))
