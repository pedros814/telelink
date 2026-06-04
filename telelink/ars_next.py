"""Build machine-readable payload for ``ars next --raw`` (Phase 2)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _quote(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return value
    if " " in value and not (value.startswith('"') and value.endswith('"')):
        return f'"{value}"'
    return value


def _action_for_state(state: str) -> str:
    if state in ("need_reply", "awaiting_agent"):
        return "reply"
    if state == "stopped":
        return "stopped"
    if state == "error":
        return "error"
    return "wait"


def _poll_after_seconds(session: dict[str, Any], config: dict[str, Any]) -> int:
    default_poll = int(
        session.get("poll_interval_seconds")
        or (config.get("ars") or {}).get("poll_interval_seconds")
        or 45
    )
    if str(session.get("state") or "") != "cooldown":
        return default_poll
    until = _parse_ts(str(session.get("cooldown_until") or ""))
    if not until:
        return default_poll
    remaining = int((until - datetime.now(timezone.utc)).total_seconds())
    return max(1, min(default_poll, remaining))


def build_next_json(
    session: dict[str, Any],
    config: dict[str, Any],
    *,
    repo_root: Path,
    run_path: str,
) -> dict[str, Any]:
    state = str(session.get("state") or "starting")
    action = _action_for_state(state)
    name = str(session.get("session") or "")

    contact = session.get("contact_resolved") or {}
    contact_name = str(contact.get("name") or session.get("contact_query") or "")
    contact_phone = str(contact.get("phone") or "")
    contact_target = contact_name or contact_phone
    q_contact = _quote(contact_target)

    commands: dict[str, str] = {
        "poll": f"{run_path} ars next {name} --raw",
        "status": f"{run_path} ars status {name} --raw",
        "tick": f"{run_path} ars tick {name} --raw",
    }

    if action == "reply":
        commands.update(
            {
                "tone": f"{run_path} agent context",
                "thread": f"{run_path} convo {q_contact} --raw",
                "inbound": f"{run_path} received {q_contact}",
                "send": f"{run_path} send {q_contact} <draft your message here>",
                "ack": f"{run_path} ars ack {name}",
            }
        )
    elif action == "stopped":
        commands.update(
            {
                "list": f"{run_path} ars list --raw",
                "start": f"{run_path} ars start {name} {q_contact}",
            }
        )
    elif action == "error":
        commands.update(
            {
                "stop": f"{run_path} ars stop {name}",
                "list": f"{run_path} ars list --raw",
            }
        )

    payload: dict[str, Any] = {
        "session": name,
        "state": state,
        "action": action,
        "needs_tending": action == "reply",
        "reason": (session.get("last_tending") or {}).get("reason")
        or (session.get("thread_cursor") or {}).get("last_eval_reason")
        or "",
        "contact": {
            "query": session.get("contact_query"),
            "name": contact_name,
            "phone": contact_phone,
        },
        "pending_inbound": session.get("pending"),
        "commands": commands,
        "poll_after_seconds": _poll_after_seconds(session, config),
        "repo_root": str(repo_root),
        "run": run_path,
    }

    if state == "starting":
        payload["bootstrapping"] = True
    if state == "awaiting_agent":
        payload["awaiting_send"] = True
        # Check if outbound was already detected while awaiting
        last_tending = session.get("last_tending") or {}
        if last_tending.get("outbound_matched"):
            payload["outbound_detected"] = True
            payload["stop_waiting"] = True
            payload["action"] = "wait"
            payload["needs_tending"] = False
    if state == "cooldown":
        payload["cooldown_until"] = session.get("cooldown_until")
    if state == "error":
        payload["error"] = (session.get("errors") or [{}])[-1].get("message", "unknown error")

    # Stale agent flag: need_reply with stale_agent marker from state machine
    if session.get("stale_agent"):
        payload["stale_agent"] = True

    # Agent rules on reply action
    if payload.get("action") == "reply":
        payload["agent_rules"] = [
            "Draft the send body yourself using owner.talking_tone from agent context",
            "Do not paste @tone into the SMS",
            "Do not read data/ars/ files — use these commands only",
            "Pause and wait for the user's reply after answering a question; do not double-text or send follow-ups immediately.",
            "Ensure pricing and facts are consistent; do not contradict previous statements in the same message.",
        ]

    return payload
