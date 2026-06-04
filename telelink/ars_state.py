"""Pure ARS state transition helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from telelink.ars_logic import body_hash

ARS_STATES = frozenset(
    {
        "starting",
        "waiting",
        "need_reply",
        "awaiting_agent",
        "cooldown",
        "paused",
        "stopped",
        "error",
    }
)


class ArsEvent(str, Enum):
    TICK = "tick"
    BOOTSTRAP_DONE = "bootstrap_done"
    INBOUND_NEEDS_REPLY = "inbound_needs_reply"
    INBOUND_SATISFIED = "inbound_satisfied"
    AGENT_ACK = "agent_ack"
    OUTBOUND_DETECTED = "outbound_detected"
    OUTBOUND_TIMEOUT = "outbound_timeout"
    CONTACT_REPLIED_AGAIN = "contact_replied_again"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    SYNC_FAILED = "sync_failed"
    UNHANDLED_ERROR = "unhandled_error"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_event(event: ArsEvent | str) -> str:
    if isinstance(event, ArsEvent):
        return event.value
    return str(event or "").strip().lower()


def _normalize_state(value: Any) -> str:
    state = str(value or "starting").strip().lower()
    return state if state in ARS_STATES else "starting"


def _pending_from_ctx(ctx: dict[str, Any]) -> dict[str, Any]:
    pending = ctx.get("pending")
    if isinstance(pending, dict):
        return deepcopy(pending)

    pending = ctx.get("pending_inbound")
    if isinstance(pending, dict):
        return deepcopy(pending)

    inbound = ctx.get("inbound")
    if not isinstance(inbound, dict):
        inbound = ctx.get("inbound_row")
    if isinstance(inbound, dict):
        body = str(inbound.get("body") or inbound.get("text") or "").strip()
        return {
            "inbound_id": str(inbound.get("id") or inbound.get("message_id") or inbound.get("rowid") or ""),
            "at": str(inbound.get("timestamp") or inbound.get("when") or ""),
            "body_preview": body[:120],
            "inbound_body_hash": body_hash(body),
            "needs_tending": True,
            "reason": str(ctx.get("reason") or "inbound_after_last_outbound"),
        }
    return {}


def _merge_cursor(session: dict[str, Any], ctx: dict[str, Any]) -> None:
    cursor = session.get("thread_cursor")
    if not isinstance(cursor, dict):
        cursor = {}
    payload = ctx.get("thread_cursor")
    if isinstance(payload, dict):
        cursor.update({k: v for k, v in payload.items() if v is not None})

    last_outbound = ctx.get("last_outbound")
    if isinstance(last_outbound, dict):
        timestamp = str(last_outbound.get("timestamp") or last_outbound.get("when") or "")
        if timestamp:
            cursor["last_outbound_at"] = timestamp
        out_body = str(last_outbound.get("body") or last_outbound.get("text") or "").strip()
        if out_body:
            cursor["last_outbound_body_hash"] = body_hash(out_body)
    session["thread_cursor"] = cursor


def _append_error(session: dict[str, Any], message: str) -> None:
    errors = session.get("errors")
    if not isinstance(errors, list):
        errors = []
    errors.append({"at": _utc_now_iso(), "error": message})
    session["errors"] = errors


def _enter_cooldown(session: dict[str, Any], ctx: dict[str, Any], *, count_turn: bool) -> None:
    session["state"] = "cooldown"
    session["pending"] = {}
    session.pop("stale_agent", None)
    session["cooldown_started_at"] = str(ctx.get("at") or _utc_now_iso())
    _merge_cursor(session, ctx)
    session["last_action"] = {"type": "outbound_detected", "at": _utc_now_iso()}
    if count_turn:
        session["turn_count"] = int(session.get("turn_count") or 0) + 1


def _cooldown_elapsed(session: dict[str, Any], ctx: dict[str, Any]) -> bool:
    direct = ctx.get("cooldown_elapsed")
    if isinstance(direct, bool):
        return direct

    elapsed_seconds = ctx.get("elapsed_seconds")
    if elapsed_seconds is not None:
        try:
            elapsed = float(elapsed_seconds)
        except (TypeError, ValueError):
            elapsed = 0.0
        cooldown = float(ctx.get("cooldown_seconds") or session.get("cooldown_seconds") or 30)
        return elapsed >= cooldown

    cooldown = float(ctx.get("cooldown_seconds") or session.get("cooldown_seconds") or 30)
    start = _parse_dt(session.get("cooldown_started_at") or session.get("updated_at"))
    now = _parse_dt(ctx.get("now") or ctx.get("at")) or datetime.now(timezone.utc)
    if start is None:
        return False
    return (now - start).total_seconds() >= cooldown


def transition(
    session_dict: dict[str, Any] | None,
    event: ArsEvent | str,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Apply a single transition from the plan's §6A table.

    Returns a new dict and never mutates the input.
    """
    session = deepcopy(session_dict or {})
    session.setdefault("turn_count", 0)
    state = _normalize_state(session.get("state"))
    session["state"] = state
    ctx = dict(ctx or {})
    event_name = _as_event(event)

    if event_name == ArsEvent.PAUSE.value and state != "paused":
        session["paused_from"] = state
        session["state"] = "paused"
    elif event_name == ArsEvent.RESUME.value and state == "paused":
        session["state"] = _normalize_state(session.get("paused_from") or "waiting")
        session.pop("paused_from", None)
    elif event_name == ArsEvent.STOP.value:
        session["state"] = "stopped"
        session.pop("pid", None)
        session.pop("process_id", None)
    else:
        if state == "starting" and event_name == ArsEvent.BOOTSTRAP_DONE.value:
            if bool(ctx.get("needs_tending")) and not session.get("no_bootstrap_reply"):
                pending = _pending_from_ctx(ctx)
                if pending:
                    session["pending"] = pending
                session["state"] = "need_reply"
            else:
                _merge_cursor(session, ctx)
                session["state"] = "waiting"

        elif state == "waiting" and event_name == ArsEvent.INBOUND_NEEDS_REPLY.value:
            pending = _pending_from_ctx(ctx)
            if pending:
                session["pending"] = pending
            session["state"] = "need_reply"

        elif state == "waiting" and event_name == ArsEvent.INBOUND_SATISFIED.value:
            _merge_cursor(session, ctx)
            session["state"] = "waiting"

        elif state == "need_reply" and event_name == ArsEvent.AGENT_ACK.value:
            pending = session.get("pending")
            if not isinstance(pending, dict):
                pending = {}
            pending["ack_at"] = str(ctx.get("at") or _utc_now_iso())
            session["pending"] = pending
            session["state"] = "awaiting_agent"
            session["last_action"] = {"type": "agent_ack", "at": _utc_now_iso()}

        elif state == "need_reply" and event_name == ArsEvent.OUTBOUND_DETECTED.value:
            _enter_cooldown(session, ctx, count_turn=False)

        elif state == "awaiting_agent" and event_name == ArsEvent.OUTBOUND_DETECTED.value:
            _enter_cooldown(session, ctx, count_turn=True)

        elif state == "awaiting_agent" and event_name == ArsEvent.AGENT_ACK.value and bool(
            ctx.get("already_outbound") or ctx.get("outbound_already")
        ):
            _enter_cooldown(session, ctx, count_turn=True)

        elif state == "awaiting_agent" and event_name == ArsEvent.OUTBOUND_TIMEOUT.value:
            session["state"] = "need_reply"
            session["stale_agent"] = True

        elif state == "awaiting_agent" and event_name == ArsEvent.INBOUND_NEEDS_REPLY.value:
            pending = _pending_from_ctx(ctx)
            if pending:
                session["pending"] = pending
            session["state"] = "need_reply"
            session["superseded_pending"] = True

        elif state == "cooldown" and event_name == ArsEvent.TICK.value:
            session["state"] = "waiting" if _cooldown_elapsed(session, ctx) else "cooldown"

        elif state == "waiting" and event_name == ArsEvent.CONTACT_REPLIED_AGAIN.value:
            pending = _pending_from_ctx(ctx)
            if pending:
                session["pending"] = pending
            session["state"] = "need_reply"

        elif state == "cooldown" and event_name == ArsEvent.CONTACT_REPLIED_AGAIN.value:
            pending = _pending_from_ctx(ctx)
            if pending:
                session["pending"] = pending
            session["state"] = "need_reply"

        elif event_name in (ArsEvent.UNHANDLED_ERROR.value, "error"):
            session["state"] = "error"
            _append_error(session, str(ctx.get("error") or "unhandled error"))

        elif ctx.get("error"):
            session["state"] = "error"
            _append_error(session, str(ctx.get("error")))

    max_turns = session.get("max_turns")
    if max_turns and session.get("turn_count", 0) >= max_turns:
        if session["state"] not in ("stopped", "error", "paused"):
            session["state"] = "stopped"
            session["stopped_reason"] = "max_turns"

    session["updated_at"] = str(ctx.get("updated_at") or _utc_now_iso())
    return session


def fold_events(
    session_dict: dict[str, Any] | None,
    events: Iterable[ArsEvent | str | tuple[ArsEvent | str, dict[str, Any] | None]],
    *,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply multiple events in order."""
    current = deepcopy(session_dict or {})
    shared_ctx = dict(ctx or {})
    for item in events:
        event: ArsEvent | str
        event_ctx: dict[str, Any] | None
        if isinstance(item, tuple):
            event, event_ctx = item
            merged = dict(shared_ctx)
            merged.update(event_ctx or {})
            current = transition(current, event, merged)
        else:
            current = transition(current, item, shared_ctx)
    return current
