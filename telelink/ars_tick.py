"""Unified ARS tick pipeline (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from telelink.ars_detect import OutboundDetectResult, detect_outbound
from telelink.ars_logic import evaluate_needs_tending
from telelink.ars_state import transition
from telelink.ars_store import load_session, save_session
from telelink.convo import fetch_conversation
from telelink.convo_parse import ConvoQuery
from telelink.ui_stealth import ui_navigate_enabled


@dataclass
class TickResult:
    session: dict[str, Any]
    events: list[str]
    rows_source: str
    rows_count: int
    needs_tending: bool
    reason: str
    outbound_matched: bool
    error: str | None = None


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cooldown_elapsed(session: dict[str, Any]) -> bool:
    if str(session.get("state") or "") != "cooldown":
        return False
    until = _parse_ts(str(session.get("cooldown_until") or ""))
    if not until:
        return True
    return datetime.now(timezone.utc) >= until


def _event_ctx(tending: Any, outbound: OutboundDetectResult) -> dict[str, Any]:
    inbound = getattr(tending, "last_inbound", None) or {}
    outbound_row = getattr(tending, "last_outbound", None) or {}
    pending = getattr(tending, "pending_inbound", None)
    if not pending and getattr(tending, "needs_tending", False) and inbound:
        body = str(inbound.get("body") or inbound.get("text") or "").strip()
        pending = {
            "id": str(inbound.get("id") or inbound.get("message_id") or ""),
            "at": str(inbound.get("timestamp") or inbound.get("when") or ""),
            "body_preview": body[:200],
        }

    ctx: dict[str, Any] = {
        "needs_tending": bool(getattr(tending, "needs_tending", False)),
        "reason": str(getattr(tending, "reason", "")),
        "pending_inbound": pending,
        "last_inbound_id": str(inbound.get("id") or inbound.get("message_id") or ""),
        "last_inbound_at": str(inbound.get("timestamp") or inbound.get("when") or ""),
        "last_outbound_at": str(outbound_row.get("timestamp") or outbound_row.get("when") or ""),
    }
    if outbound.matched and outbound.record:
        ctx["last_outbound_at"] = str(outbound.record.get("timestamp") or outbound.record.get("when") or "")
    return ctx


def derive_events(
    session: dict[str, Any],
    *,
    tending: Any,
    outbound: OutboundDetectResult,
    config: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Phase 1 event derivation: bootstrap, inbound status, tick, cooldown elapsed."""
    ctx = _event_ctx(tending, outbound)
    events: list[tuple[str, dict[str, Any]]] = []

    if str(session.get("state") or "starting") == "starting":
        events.append(("bootstrap_done", ctx))
    else:
        state = str(session.get("state") or "")
        if bool(getattr(tending, "needs_tending", False)):
            ars_conf = config.get("ars") or {}
            if state == "cooldown" and not ars_conf.get("cooldown_interrupt_on_new_inbound", True):
                # Ignore new inbound during cooldown if config says so
                pass
            else:
                ev = "contact_replied_again" if state == "cooldown" else "inbound_needs_reply"
                events.append((ev, ctx))
        else:
            events.append(("inbound_satisfied", ctx))

    if outbound.matched:
        events.append(("outbound_detected", ctx))
    events.append(("tick", {}))
    return events


def _query_for_session(session: dict[str, Any], config: dict[str, Any]) -> ConvoQuery:
    contact = session.get("contact_resolved") or {}
    target = (
        str(contact.get("name") or "")
        or str(contact.get("phone") or "")
        or str(session.get("contact_query") or "")
    )
    limit = int(session.get("thread_limit") or (config.get("ars") or {}).get("thread_limit") or 50)
    return ConvoQuery(target=target, limit=limit)


def _maybe_sync(session: dict[str, Any], config: dict[str, Any]) -> None:
    """Run light or full sync before tick if configured (§8.2)."""
    ars_cfg = config.get("ars") or {}

    # Light sync every tick (off by default)
    if ars_cfg.get("sync_before_tick", False):
        try:
            from telelink.session import get_session
            tl = get_session()
            tl.cache.invalidate()
        except Exception:
            pass

    # Full sync periodically
    full_every = ars_cfg.get("full_sync_every")
    if full_every:
        try:
            from telelink.duration import parse_duration
            interval_secs = parse_duration(full_every) if isinstance(full_every, str) else int(full_every)
        except Exception:
            interval_secs = 900  # 15m default

        last_full = _parse_ts(str(session.get("last_full_sync_at") or ""))
        now = datetime.now(timezone.utc)
        if last_full is None or (now - last_full).total_seconds() >= interval_secs:
            try:
                from telelink.session import get_session
                from telelink.sync import run_full_sync
                tl = get_session()
                run_full_sync(tl, quiet=True)
                session["last_full_sync_at"] = now.isoformat()
            except Exception:
                pass


def run_ars_tick(
    session_name: str,
    config: dict[str, Any],
    contact_store: Any,
) -> TickResult:
    session = load_session(config, session_name)
    source = ""
    rows: list[dict[str, Any]] = []
    events_out: list[str] = []

    try:
        # Light/full sync before fetch (§8.2)
        _maybe_sync(session, config)

        query = _query_for_session(session, config)
        rows, display, phone, source = fetch_conversation(
            query,
            config=config,
            contact_store=contact_store,
            ui_navigate=ui_navigate_enabled(config, for_ars=True),
            for_ars=True,
        )
        session["contact_resolved"] = {
            "name": display or query.target,
            "phone": phone or query.target,
        }

        tending = evaluate_needs_tending(rows, session, config)
        outbound = detect_outbound(
            session,
            config,
            rows=rows,
            contact_store=contact_store,
        )
        events = derive_events(session, tending=tending, outbound=outbound, config=config)

        current = session
        for event, ctx in events:
            current = transition(current, event, ctx)
            events_out.append(event)

        current["last_tick_at"] = datetime.now(timezone.utc).isoformat()
        current["last_tending"] = {
            "needs_tending": bool(getattr(tending, "needs_tending", False)),
            "reason": str(getattr(tending, "reason", "")),
            "rows_source": source,
            "rows_count": len(rows),
            "outbound_matched": outbound.matched,
            "outbound_source": outbound.source,
        }
        saved = save_session(config, current)
        return TickResult(
            session=saved,
            events=events_out,
            rows_source=source,
            rows_count=len(rows),
            needs_tending=bool(getattr(tending, "needs_tending", False)),
            reason=str(getattr(tending, "reason", "")),
            outbound_matched=outbound.matched,
        )
    except Exception as exc:
        errored = transition(session, "error", {"error": str(exc)})
        errored["last_tick_at"] = datetime.now(timezone.utc).isoformat()
        saved = save_session(config, errored)
        return TickResult(
            session=saved,
            events=events_out or ["error"],
            rows_source=source,
            rows_count=len(rows),
            needs_tending=False,
            reason="error",
            outbound_matched=False,
            error=str(exc),
        )
