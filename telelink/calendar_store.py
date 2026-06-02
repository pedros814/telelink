"""Calendar event store — scheduled SMS and synced reminders."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from telelink.calendar_time import format_fire_at, normalize_when_expression, parse_fire_at
from telelink.db import Database

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Terminal — never picked up by scheduler or reset to pending by Google pull.
CALENDAR_TERMINAL_STATUSES = frozenset(
    {"completed", "fired", "failed", "cancelled", "skipped", "processing"}
)


def calendar_status_is_terminal(status: str | None) -> bool:
    return (status or "").strip().lower() in CALENDAR_TERMINAL_STATUSES


def slugify_name(text: str) -> str:
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug[:48] or "event"


def event_receiver_label(event: dict[str, Any]) -> str:
    """Contact name for CLI messages (from notes contact: tag, else stored to)."""
    notes = (event.get("notes") or "").strip()
    for part in notes.split(" · "):
        if part.startswith("contact:"):
            return part.split(":", 1)[1].strip() or "?"
    to = (event.get("to") or "").strip()
    if to:
        return to
    return (event.get("name") or "?").strip()


def unique_name(db: Database, base: str) -> str:
    slug = slugify_name(base)
    if not db.calendar_get_by_name(slug):
        return slug
    for i in range(2, 200):
        candidate = f"{slug}-{i}"
        if not db.calendar_get_by_name(candidate):
            return candidate
    return f"{slug}-{uuid.uuid4().hex[:6]}"


class CalendarStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def schedule_send(
        self,
        *,
        to: str,
        body: str,
        when: str,
        name: str = "",
        title: str = "",
        config: dict[str, Any] | None = None,
        notes: str = "",
        source: str = "local",
        google_event_id: str = "",
        contact_store: Any | None = None,
    ) -> dict[str, Any]:
        from telelink.contacts import looks_like_phone
        from telelink.messaging import resolve_send_recipient

        to_raw = (to or "").strip()
        if contact_store is None:
            from telelink.session import get_session

            contact_store = get_session().contact_store
        phone, display = resolve_send_recipient(to_raw, store=contact_store)

        fire_at = parse_fire_at(normalize_when_expression(when), config=config)
        event_name = name.strip() or unique_name(self.db, display or to_raw or "send")
        if self.db.calendar_get_by_name(event_name):
            raise ValueError(f"calendar event name already exists: {event_name}")
        now = datetime.now(timezone.utc).isoformat()
        note_parts = [notes] if notes else []
        if display and display != phone and not looks_like_phone(display):
            note_parts.append(f"contact:{display}")
        event = {
            "id": str(uuid.uuid4()),
            "name": event_name,
            "title": title or f"SMS to {display}",
            "kind": "send_sms",
            "to": phone,
            "body": body.strip(),
            "fire_at": format_fire_at(fire_at),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "google_event_id": google_event_id,
            "notes": " · ".join(p for p in note_parts if p),
            "error": "",
            "source": source,
        }
        if not event["to"] or not looks_like_phone(event["to"]):
            raise ValueError("recipient must resolve to a dialable +phone number")
        if not event["body"]:
            raise ValueError("message body is required")
        self.db.calendar_upsert(event)
        return event

    def delay_event(
        self,
        name: str,
        when: str,
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.db.calendar_get_by_name(name)
        if not event:
            raise ValueError(f"calendar event not found: {name}")
        if event["status"] != "pending":
            raise ValueError(
                f"event {name!r} is {event['status']} — only pending events can be delayed"
            )
        fire_at = parse_fire_at(normalize_when_expression(when), config=config)
        event["fire_at"] = format_fire_at(fire_at)
        event["updated_at"] = datetime.now(timezone.utc).isoformat()
        event["error"] = ""
        self.db.calendar_upsert(event)
        return event

    def cancel_event(self, name: str) -> dict[str, Any] | None:
        event = self.db.calendar_get_by_name(name)
        if not event:
            return None
        event["status"] = "cancelled"
        event["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.db.calendar_upsert(event)
        return event

    def delete_event(self, name: str) -> bool:
        event = self.db.calendar_get_by_name(name)
        if not event:
            return False
        return self.db.calendar_delete(event["id"])

    def list_events(self, *, all_statuses: bool = False) -> list[dict[str, Any]]:
        if all_statuses:
            return self.db.calendar_list()
        return self.db.calendar_list(pending_only=True)

    def pending_count(self) -> int:
        return self.db.calendar_count_pending()
