"""Core ARS tending logic and thread helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from telelink.received import is_incoming_row

_DEFAULT_STALE_HOURS = 72
_DEFAULT_TAPBACK_PATTERNS = (
    r"^Liked ",
    r"^Loved ",
    r"^Emphasized ",
    r"^Questioned ",
    r"^Reacted ",
)
_SESSION_CURSOR_KEYS = (
    "last_inbound_id",
    "last_inbound_at",
    "last_inbound_body_hash",
    "last_outbound_at",
    "last_outbound_body_hash",
)


@dataclass(frozen=True)
class NeedsTendingResult:
    needs_tending: bool
    reason: str
    last_inbound: dict[str, Any] | None = None
    last_outbound: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_tending": self.needs_tending,
            "reason": self.reason,
            "last_inbound": self.last_inbound,
            "last_outbound": self.last_outbound,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        n = int(value)
        if n <= 0:
            return None
        if n > 10_000_000_000_000:
            # Windows FILETIME-like ticks (100ns since 1601).
            unix = (n - 116444736000000000) / 10_000_000
            if unix > 0:
                return datetime.fromtimestamp(unix, tz=timezone.utc)
        if n > 1_000_000_000_000:
            return datetime.fromtimestamp(n / 1000.0, tz=timezone.utc)
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_dt(int(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _body(row: dict[str, Any]) -> str:
    return str(row.get("body") or row.get("text") or row.get("raw_message") or "").strip()


def body_hash(value: str | dict[str, Any]) -> str:
    """Stable sha256 for bodies (or for a row containing body/text)."""
    if isinstance(value, dict):
        body = _body(value)
    else:
        body = str(value or "").strip()
    digest = hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _row_id(row: dict[str, Any]) -> str:
    raw = row.get("id")
    if raw in (None, ""):
        raw = row.get("message_id")
    if raw in (None, ""):
        raw = row.get("rowid")
    if raw in (None, ""):
        raw = row.get("messageId")
    return str(raw or "")


def _row_id_key(row: dict[str, Any]) -> tuple[int, str]:
    rid = _row_id(row)
    if rid.isdigit():
        return (int(rid), rid)
    m = re.search(r"\d+", rid)
    if m:
        return (int(m.group(0)), rid)
    return (-1, rid)


def _row_dt(row: dict[str, Any]) -> datetime | None:
    return _parse_dt(row.get("timestamp") or row.get("when") or row.get("at") or row.get("date"))


def parse_thread_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return rows sorted chronologically (oldest -> newest)."""
    clean = [dict(row) for row in (rows or []) if isinstance(row, dict)]

    def _sort_key(row: dict[str, Any]) -> tuple[datetime, int, str]:
        dt = _row_dt(row) or datetime.min.replace(tzinfo=timezone.utc)
        rid_num, rid_raw = _row_id_key(row)
        return (dt, rid_num, rid_raw)

    clean.sort(key=_sort_key)
    return clean


def _is_actually_outbound(row: dict[str, Any], config: dict[str, Any] | None) -> bool:
    if not config:
        return False
    from telelink.sent_log import sent_log_path
    import json
    path = sent_log_path(config)
    if not path.exists():
        return False
    body = _body(row)
    if not body:
        return False
    dt = _row_dt(row)
    now = _utc_now()
    if dt and (now - dt).total_seconds() > 86400:
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    sent_body = str(record.get("body") or "").strip()
                    if sent_body and sent_body == body:
                        sent_ts = _parse_dt(record.get("timestamp"))
                        if sent_ts and dt:
                            if abs((sent_ts - dt).total_seconds()) < 600:
                                return True
                        else:
                            return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def last_inbound_row(rows: list[dict[str, Any]] | None, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ordered = parse_thread_rows(rows)
    for row in reversed(ordered):
        if not _body(row):
            continue
        if is_incoming_row(row):
            if _is_actually_outbound(row, config):
                continue
            return row
    return None


def last_outbound_row(rows: list[dict[str, Any]] | None, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ordered = parse_thread_rows(rows)
    for row in reversed(ordered):
        if not _body(row):
            continue
        if not is_incoming_row(row) or _is_actually_outbound(row, config):
            return row
    return None


def _tapback_patterns(config: dict[str, Any] | None) -> list[str]:
    ars = (config or {}).get("ars") or {}
    patterns = ars.get("tapback_patterns")
    if isinstance(patterns, list):
        out = [str(p).strip() for p in patterns if str(p).strip()]
        if out:
            return out
    return list(_DEFAULT_TAPBACK_PATTERNS)


def _is_tapback_only(row: dict[str, Any], *, config: dict[str, Any] | None) -> bool:
    body = _body(row)
    if not body:
        return False
    for pattern in _tapback_patterns(config):
        try:
            if re.search(pattern, body, flags=re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in body.lower():
                return True
    return False


def _ignore_stale_hours(config: dict[str, Any] | None) -> float:
    ars = (config or {}).get("ars") or {}
    raw = ars.get("ignore_stale_hours", _DEFAULT_STALE_HOURS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(_DEFAULT_STALE_HOURS)
    return value if value > 0 else float(_DEFAULT_STALE_HOURS)


def _inbound_is_stale(row: dict[str, Any], *, config: dict[str, Any] | None) -> bool:
    dt = _row_dt(row)
    if dt is None:
        return False
    age_seconds = (_utc_now() - dt).total_seconds()
    return age_seconds > (_ignore_stale_hours(config) * 3600.0)


def _id_greater(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_num, a_raw = _row_id_key(a)
    b_num, b_raw = _row_id_key(b)
    if a_num >= 0 and b_num >= 0:
        return a_num > b_num
    return a_raw > b_raw


def _already_handled(
    session: dict[str, Any] | None,
    *,
    last_inbound: dict[str, Any],
    last_outbound: dict[str, Any],
) -> bool:
    if not isinstance(session, dict):
        return False

    pending = session.get("pending") or {}
    cursor = session.get("thread_cursor") or {}
    inbound_id = _row_id(last_inbound)
    inbound_hash = body_hash(last_inbound)
    outbound_hash = body_hash(last_outbound)
    inbound_dt = _row_dt(last_inbound)
    outbound_dt = _row_dt(last_outbound)

    if isinstance(pending, dict):
        pending_id = str(pending.get("inbound_id") or pending.get("id") or "")
        pending_hash = str(
            pending.get("inbound_body_hash")
            or pending.get("body_hash")
            or pending.get("last_inbound_body_hash")
            or ""
        )
        expected_out_hash = str(
            pending.get("expected_outbound_hash")
            or pending.get("handled_by_outbound_hash")
            or ""
        )
        ack_at = _parse_dt(pending.get("ack_at"))
        if pending_id and pending_id == inbound_id:
            if expected_out_hash and expected_out_hash == outbound_hash:
                return True
            if ack_at is not None and outbound_dt is not None and outbound_dt >= ack_at:
                return True
        if pending_hash and pending_hash == inbound_hash and expected_out_hash:
            if expected_out_hash == outbound_hash:
                return True

    if isinstance(cursor, dict):
        cursor_in_id = str(cursor.get("last_inbound_id") or "")
        cursor_in_hash = str(cursor.get("last_inbound_body_hash") or "")
        cursor_out_hash = str(cursor.get("last_outbound_body_hash") or "")
        cursor_out_at = _parse_dt(cursor.get("last_outbound_at"))

        inbound_matches_cursor = (cursor_in_id and cursor_in_id == inbound_id) or (
            cursor_in_hash and cursor_in_hash == inbound_hash
        )
        if inbound_matches_cursor and cursor_out_hash and cursor_out_hash == outbound_hash:
            return True
        if inbound_matches_cursor and inbound_dt and outbound_dt and outbound_dt >= inbound_dt:
            if cursor_out_at and cursor_out_at >= inbound_dt:
                return True

    return False


def needs_tending(
    rows: list[dict[str, Any]] | None,
    session: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> NeedsTendingResult:
    """Evaluate whether latest inbound requires a reply."""
    ordered = parse_thread_rows(rows)
    rows_with_body = [row for row in ordered if _body(row)]
    if not rows_with_body:
        return NeedsTendingResult(False, "empty_thread")

    last_inbound = last_inbound_row(ordered, config)
    last_outbound = last_outbound_row(ordered, config)

    if last_inbound is None:
        return NeedsTendingResult(False, "no_inbound", last_inbound=None, last_outbound=last_outbound)

    if _is_tapback_only(last_inbound, config=config):
        return NeedsTendingResult(False, "tapback_only", last_inbound=last_inbound, last_outbound=last_outbound)

    if not force and _inbound_is_stale(last_inbound, config=config):
        return NeedsTendingResult(False, "stale", last_inbound=last_inbound, last_outbound=last_outbound)

    ars_conf = (config or {}).get("ars") or {}
    if ars_conf.get("burst_coalesce", True):
        quiet_secs = float(ars_conf.get("burst_quiet_seconds") or 15.0)
        dt = _row_dt(last_inbound)
        source = last_inbound.get("source", "")
        if dt and not force and "phone_link_ui" not in source:
            age = (_utc_now() - dt).total_seconds()
            if age >= 0 and age < quiet_secs:
                return NeedsTendingResult(False, "burst_active", last_inbound=last_inbound, last_outbound=last_outbound)

    if last_outbound is None:
        return NeedsTendingResult(True, "never_replied", last_inbound=last_inbound, last_outbound=None)

    inbound_dt = _row_dt(last_inbound)
    outbound_dt = _row_dt(last_outbound)
    if inbound_dt and outbound_dt:
        if inbound_dt > outbound_dt:
            reason = "inbound_after_last_outbound"
            if ars_conf.get("burst_coalesce", True):
                window = float(ars_conf.get("burst_window", 90.0))
                # Check if there are multiple inbounds since last outbound within window
                inbounds_since = [r for r in ordered if _body(r) and is_incoming_row(r) and _row_dt(r) and _row_dt(r) > outbound_dt]
                if len(inbounds_since) > 1 and (_utc_now() - _row_dt(inbounds_since[0])).total_seconds() <= window:
                    reason = "inbound_burst_coalesced"
            return NeedsTendingResult(True, reason, last_inbound=last_inbound, last_outbound=last_outbound)
        if inbound_dt == outbound_dt and body_hash(last_inbound) != body_hash(last_outbound):
            if _id_greater(last_inbound, last_outbound):
                return NeedsTendingResult(
                    True,
                    "inbound_after_last_outbound",
                    last_inbound=last_inbound,
                    last_outbound=last_outbound,
                )

    if _already_handled(session, last_inbound=last_inbound, last_outbound=last_outbound):
        return NeedsTendingResult(
            False,
            "already_handled",
            last_inbound=last_inbound,
            last_outbound=last_outbound,
        )

    return NeedsTendingResult(False, "already_replied", last_inbound=last_inbound, last_outbound=last_outbound)


# Plan wording uses this name in examples.
evaluate_needs_tending = needs_tending


def session_cursor_from_rows(rows: list[dict[str, Any]] | None) -> dict[str, str]:
    """Build thread_cursor payload from the latest inbound/outbound rows."""
    ordered = parse_thread_rows(rows)
    inbound = last_inbound_row(ordered)
    outbound = last_outbound_row(ordered)
    cursor = {key: "" for key in _SESSION_CURSOR_KEYS}
    if inbound:
        cursor["last_inbound_id"] = _row_id(inbound)
        cursor["last_inbound_at"] = str(inbound.get("timestamp") or inbound.get("when") or "")
        cursor["last_inbound_body_hash"] = body_hash(inbound)
    if outbound:
        cursor["last_outbound_at"] = str(outbound.get("timestamp") or outbound.get("when") or "")
        cursor["last_outbound_body_hash"] = body_hash(outbound)
    return cursor
