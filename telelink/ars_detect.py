"""Outbound detection for ARS — Phase 2.

Detection order (first match wins) per §6B:
  1. sent_log  — data/sent.jsonl rows matching session contact
  2. phone_db  — convo thread rows with outbound after pending inbound
  3. agent_ack — ctx["force_ack"] from ``ars ack --force``

All config keys live under ``ars.*`` (detect_send_via_sent_log, detect_send_via_convo,
sent_match_window, assume_clicked_is_sent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from telelink.received import is_incoming_row


@dataclass(frozen=True)
class OutboundDetectResult:
    matched: bool = False
    source: str | None = None          # "sent_log" | "phone_db" | "agent_force"
    record: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\D")


def _digits(value: str) -> str:
    """Keep only digits for phone comparison."""
    return _DIGITS_RE.sub("", value or "")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Unix timestamp (seconds or milliseconds)
    try:
        n = float(text)
        if n > 1e12:
            n /= 1000.0
        if n > 1e8:
            return datetime.fromtimestamp(n, tz=timezone.utc)
    except (ValueError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _body_text(row: dict[str, Any]) -> str:
    return str(row.get("body") or row.get("text") or row.get("raw_message") or "").strip()


def _contact_dials(session: dict[str, Any]) -> set[str]:
    """Return set of digit-only phone representations for matching sent_log."""
    resolved = session.get("contact_resolved") or {}
    phone = str(resolved.get("phone") or "")
    query = str(session.get("contact_query") or "")
    dials: set[str] = set()
    for raw in (phone, query):
        d = _digits(raw)
        if len(d) >= 7:
            dials.add(d)
            if len(d) > 10:
                dials.add(d[-10:])  # last 10 digits
    return dials


def _pending_ts(session: dict[str, Any]) -> datetime | None:
    """Earliest timestamp for the current pending inbound (or ack_at)."""
    pending = session.get("pending") or {}
    for key in ("ack_at", "started_at", "at", "inbound_at"):
        ts = _parse_ts(pending.get(key))
        if ts:
            return ts
    # Fallback: pending.at or updated_at of session
    ts = _parse_ts(session.get("updated_at"))
    return ts


def _match_window(config: dict[str, Any]) -> timedelta:
    ars = config.get("ars") or {}
    raw = ars.get("sent_match_window")
    if raw is None:
        return timedelta(minutes=30)
    try:
        from telelink.duration import parse_duration
        secs = parse_duration(raw)
        return timedelta(seconds=secs)
    except Exception:
        return timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Source 1: sent_log
# ---------------------------------------------------------------------------

def _detect_via_sent_log(
    session: dict[str, Any],
    config: dict[str, Any],
) -> OutboundDetectResult:
    """Check data/sent.jsonl for outbound matching session contact after pending."""
    from telelink.sent_log import sent_log_path

    path = sent_log_path(config)
    if not path.exists():
        return OutboundDetectResult()

    dials = _contact_dials(session)
    if not dials:
        return OutboundDetectResult()

    pending_start = _pending_ts(session)
    window = _match_window(config)
    now = datetime.now(timezone.utc)

    # Read sent log lines (small file — read all)
    import json
    lines: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return OutboundDetectResult()

    ars_cfg = config.get("ars") or {}
    assume_clicked = bool(ars_cfg.get("assume_clicked_is_sent", False))

    # Walk newest first
    for record in reversed(lines):
        # Check contact match
        record_dial = _digits(str(record.get("dial") or record.get("to_phone") or ""))
        if not record_dial:
            continue
        # Match by dial digits (last 10)
        matched = False
        for d in dials:
            if record_dial == d or record_dial.endswith(d) or d.endswith(record_dial):
                matched = True
                break
        if not matched:
            continue

        # Check timestamp within window
        ts = _parse_ts(record.get("timestamp"))
        if ts is None:
            continue
        if ts < now - window:
            break  # too old; everything after is older
        if pending_start and ts < pending_start:
            continue  # before current pending

        # Check if actually sent
        auto_sent = record.get("auto_sent")
        send_clicked = record.get("send_clicked")
        send_verified = record.get("send_verified")

        if auto_sent:
            return OutboundDetectResult(matched=True, source="sent_log", record=record)
        if send_verified:
            return OutboundDetectResult(matched=True, source="sent_log", record=record)
        if send_clicked and assume_clicked:
            return OutboundDetectResult(matched=True, source="sent_log", record=record)
        # send_clicked but not verified and not assume → don't match yet (wait for convo)
        if send_clicked:
            continue
        # Record exists but no auto_sent/send_clicked — still a valid sent log entry
        # (could be manual method or legacy format)
        body = str(record.get("body") or "").strip()
        if body:
            return OutboundDetectResult(matched=True, source="sent_log", record=record)

    return OutboundDetectResult()


# ---------------------------------------------------------------------------
# Source 2: convo thread rows
# ---------------------------------------------------------------------------

def _detect_via_convo(
    session: dict[str, Any],
    config: dict[str, Any],
    rows: list[dict[str, Any]] | None,
) -> OutboundDetectResult:
    """Check convo thread rows for outbound after pending inbound."""
    if not rows:
        return OutboundDetectResult()

    pending = session.get("pending") or {}
    pending_at = _parse_ts(pending.get("at") or pending.get("inbound_at"))

    # Find last outbound row
    last_outbound: dict[str, Any] | None = None
    for row in reversed(rows):
        if is_incoming_row(row):
            continue
        body = _body_text(row)
        if not body:
            continue
        last_outbound = row
        break

    if last_outbound is None:
        return OutboundDetectResult()

    outbound_ts = _parse_ts(
        last_outbound.get("timestamp")
        or last_outbound.get("when")
        or last_outbound.get("at")
    )

    if pending_at and outbound_ts and outbound_ts < pending_at:
        return OutboundDetectResult()  # outbound is before pending inbound

    # If we reach here, there's an outbound after (or concurrent with) the pending inbound
    return OutboundDetectResult(matched=True, source="phone_db", record=last_outbound)


# ---------------------------------------------------------------------------
# Source 3: agent force ack
# ---------------------------------------------------------------------------

def _detect_via_force_ack(ctx: dict[str, Any] | None) -> OutboundDetectResult:
    """Handle ``ars ack --force`` — agent confirms manual send on phone."""
    if not ctx:
        return OutboundDetectResult()
    if ctx.get("force_ack"):
        return OutboundDetectResult(
            matched=True,
            source="agent_force",
            record={"force_ack": True, "at": datetime.now(timezone.utc).isoformat()},
        )
    return OutboundDetectResult()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_outbound(
    session: dict[str, Any],
    config: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
    contact_store: Any = None,
    ctx: dict[str, Any] | None = None,
) -> OutboundDetectResult:
    """Detect whether outbound SMS was sent for the current pending inbound.

    Detection order (§6B):
      1. ``sent_log`` — fast, check data/sent.jsonl
      2. ``phone_db`` — authoritative, check convo thread rows
      3. ``agent_force`` — ``ars ack --force``

    Only runs detection when session is in a state that expects outbound
    (need_reply, awaiting_agent).
    """
    state = str(session.get("state") or "")
    if state not in ("need_reply", "awaiting_agent"):
        return OutboundDetectResult()

    ars_cfg = config.get("ars") or {}

    # 1. Force ack (explicit)
    result = _detect_via_force_ack(ctx)
    if result.matched:
        return result

    # 2. Sent log (fast)
    if ars_cfg.get("detect_send_via_sent_log", True):
        result = _detect_via_sent_log(session, config)
        if result.matched:
            return result

    # 3. Convo thread (authoritative)
    if ars_cfg.get("detect_send_via_convo", True):
        result = _detect_via_convo(session, config, rows)
        if result.matched:
            return result

    return OutboundDetectResult()
