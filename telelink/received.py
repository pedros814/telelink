"""Agent-friendly: what did a contact send me? (incoming SMS only, full bodies)."""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from telelink.convo import fetch_conversation
from telelink.convo_parse import ConvoQuery
from telelink.json_out import print_json
from telelink.ora import ora
from telelink.session import get_session


def is_incoming_row(row: dict[str, Any]) -> bool:
    direction = str(row.get("direction") or "").lower()
    if direction in ("in", "incoming", "received"):
        return True
    if direction in ("out", "outgoing", "sent"):
        return False
    if row.get("incoming") is True:
        return True
    if row.get("incoming") is False:
        return False
    from_addr = str(row.get("from_address") or "").lower()
    if from_addr and from_addr not in ("you", "me", "myself"):
        return True
    return False


def agent_message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": row.get("timestamp") or row.get("when") or "",
        "from": row.get("from_address") or row.get("peer_name") or "",
        "body": (row.get("body") or row.get("text") or "").strip(),
    }


def build_received_payload(
    rows: list[dict[str, Any]],
    *,
    display: str,
    phone: str,
    source: str,
    limit: int | None,
) -> dict[str, Any]:
    incoming = [r for r in rows if is_incoming_row(r)]
    incoming.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    if limit is not None:
        incoming = incoming[: max(1, limit)]

    messages = [agent_message(r) for r in incoming]
    messages = [m for m in messages if m.get("body")]

    return {
        "contact": display or phone,
        "phone": phone,
        "count": len(messages),
        "messages": messages,
        "source": source,
    }


def cmd_received(args: Namespace) -> int:
    from telelink import pretty
    from telelink.convo_parse import parse_convo_tokens, strip_cli_flags

    config = get_session().config_fresh()
    rest = [str(x) for x in (getattr(args, "rest", None) or []) if str(x).strip()]
    cli_limit = getattr(args, "limit", None)
    if rest:
        rest, _, _ = strip_cli_flags(rest)
        try:
            query = parse_convo_tokens(rest, config=config)
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1
        query.incoming_only = True
        if cli_limit is not None:
            query.limit = cli_limit
    else:
        target = str(getattr(args, "target", "") or "").strip()
        if not target:
            pretty.warn(
                "usage: received <contact|+number>  ·  received mom  ·  received last 5 mom"
            )
            return 1
        query = ConvoQuery(
            target=target,
            limit=cli_limit or 20,
            incoming_only=True,
        )

    with ora("Loading messages", kind="load"):
        try:
            rows, display, phone, source = fetch_conversation(
                query,
                config=config,
                contact_store=get_session().contact_store,
            )
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1

    payload = build_received_payload(
        rows,
        display=display or query.target,
        phone=phone,
        source=source,
        limit=query.limit,
    )
    print_json(payload)
    return 0
