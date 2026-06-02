"""Parse send lines — immediate SMS or schedule via in%<when>% prefix."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

_IN_PERCENT_RE = re.compile(r"^in%(.*)%$", re.IGNORECASE | re.DOTALL)
# in1m, in20s, in2hour — no % required
_IN_SHORTHAND_RE = re.compile(
    r"^in(\d+(?:\.\d+)?)(hours?|hrs?|h|minutes?|mins?|minute|m|seconds?|secs?|sec|s|days?|day|d)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SendImmediate:
    to: str
    body: str


@dataclass(frozen=True)
class SendScheduled:
    when_raw: str
    to: str
    body: str


SendIntent = SendImmediate | SendScheduled


def clean_send_who(token: str) -> str:
    """Strip optional %name% wrappers; normalize contact/phone."""
    from telelink.contacts import clean_send_target

    t = (token or "").strip()
    if len(t) >= 2 and t.startswith("%") and t.endswith("%"):
        t = t[1:-1].strip()
    return clean_send_target(t)


def _extract_in_percent_time(tokens: list[str]) -> tuple[str, list[str]] | None:
    """If tokens start with in%...%, return (when_inner, rest). Supports multi-token time."""
    if not tokens:
        return None
    if not tokens[0].lower().startswith("in%"):
        return None

    combined = tokens[0]
    end_idx = 0
    for i, tok in enumerate(tokens):
        combined = tokens[0] if i == 0 else " ".join(tokens[: i + 1])
        if tok.endswith("%"):
            end_idx = i
            break
    else:
        raise ValueError(
            'schedule time must end with % — e.g. send in%2hour% "Contact" your message'
        )

    m = _IN_PERCENT_RE.match(combined.strip())
    if not m:
        raise ValueError(f"invalid schedule prefix: {combined!r} — use in%<when>%")
    when_inner = m.group(1).strip()
    if not when_inner:
        raise ValueError("schedule time between % markers is empty — e.g. in%2hour%")
    return when_inner, tokens[end_idx + 1 :]


def _extract_in_shorthand_time(tokens: list[str]) -> tuple[str, list[str]] | None:
    """in1m, in2hour, in30min — glued form without % markers."""
    if not tokens:
        return None
    m = _IN_SHORTHAND_RE.match(tokens[0].strip())
    if not m:
        return None
    amount = m.group(1).strip()
    unit = (m.group(2) or "").strip()
    when_inner = f"{amount}{unit}" if unit else amount
    if not when_inner:
        return None
    return when_inner, tokens[1:]


def _extract_schedule_prefix(tokens: list[str]) -> tuple[str, list[str]] | None:
    return _extract_in_percent_time(tokens) or _extract_in_shorthand_time(tokens)


def parse_send_tokens(tokens: list[str]) -> SendIntent:
    if len(tokens) < 2:
        raise ValueError(
            'usage: send <contact|+number> <message>\n'
            '       send in1m <contact> <message>  — or  send in%2hour% <contact> <message>'
        )

    schedule = _extract_schedule_prefix(tokens)
    if schedule is not None:
        when_raw, rest = schedule
        if len(rest) < 2:
            raise ValueError(
                'usage: send in1m <contact> <message>  — or  send in%2hour% <contact> <message>'
            )
        to = clean_send_who(rest[0])
        body = " ".join(rest[1:])
        if not body.strip():
            raise ValueError("message body is required")
        return SendScheduled(when_raw=when_raw, to=to, body=body.strip())

    to = clean_send_who(tokens[0])
    body = " ".join(tokens[1:])
    if not body.strip():
        raise ValueError("message body is required")
    return SendImmediate(to=to, body=body.strip())


def parse_send_line(text: str) -> SendIntent:
    return parse_send_tokens(shlex.split(text, posix=True))


def run_send_intent(intent: SendIntent, *, config: dict[str, Any] | None = None) -> int:
    """Execute immediate send or schedule calendar event. Returns exit code."""
    from telelink.session import get_session

    session = get_session()
    config = config or session.config_fresh()

    if isinstance(intent, SendScheduled):
        return _run_scheduled(intent, config)

    return _run_immediate(intent, config)


def _run_scheduled(intent: SendScheduled, config: dict[str, Any]) -> int:
    from telelink import pretty
    from telelink.calendar import _maybe_google_push, _print_scheduled
    from telelink.calendar_store import CalendarStore, slugify_name, unique_name
    from telelink.calendar_time import normalize_when_expression, parse_fire_at  # noqa: PLC2701
    from telelink.session import get_session

    cal_cfg = config.get("calendar") or {}
    if cal_cfg.get("enabled", True) is False:
        pretty.warn("calendar is disabled — config edit calendar_enabled true")
        return 1

    when = normalize_when_expression(intent.when_raw)
    try:
        parse_fire_at(when, config=config)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    db = get_session().db
    store = CalendarStore(db)
    base = slugify_name(f"{intent.to}-{intent.when_raw}")
    name = unique_name(db, base)
    try:
        event = store.schedule_send(
            to=intent.to,
            body=intent.body,
            when=when,
            name=name,
            config=config,
            contact_store=get_session().contact_store,
        )
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    _print_scheduled(event, config)
    _maybe_google_push(config, event)
    return 0


def _run_immediate(intent: SendImmediate, config: dict[str, Any]) -> int:
    from telelink import chalk, pretty
    from telelink.messaging import send_to_target
    from telelink.session import get_session

    if not config.get("messaging", {}).get("enabled", True):
        pretty.warn("messaging is disabled in config.yaml (messaging.enabled)")
        return 1

    store = get_session().contact_store
    try:
        record = send_to_target(intent.to, intent.body, store=store, config=config)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    dial = record.get("dial") or record["to_phone"]
    pretty.info("SEND", f"{dial}")
    if record.get("to_name") and record["to_name"] != record["to_phone"]:
        print(f"  {chalk.muted('contact:')} {chalk.value(str(record['to_name']))}")
    print(f"  {chalk.plain(record['body'][:200])}")

    note = record.get("note") or ""
    method = str(record.get("method") or "")
    verified = record.get("send_verified")
    clicked = record.get("send_clicked")

    if record.get("auto_sent"):
        print(f"\n  {chalk.baby('sent')} ({chalk.value(method)})")
        if verified and record.get("verify_method"):
            print(f"  {chalk.muted('verified:')} {chalk.value(str(record.get('verify_method')))}")
        if note:
            print(f"  {chalk.muted(note)}")
    elif clicked:
        print(f"\n  {chalk.label('send not verified')} ({chalk.value(method)})")
        if record.get("verify_method"):
            print(f"  {chalk.muted('verify:')} {chalk.value(str(record.get('verify_method')))}")
        if note:
            print(f"  {chalk.muted(note)}")
    else:
        print(f"\n  {chalk.muted(note or 'Compose opened — tap Send in Phone Link.')}")

    print(
        f"\n  {chalk.muted('Tip: set messaging.method: auto in config.yaml for UI auto-send (best effort).')}\n"
    )
    return 0
