"""SQLite store — canonical contacts + KV overlay."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    aliases_json TEXT DEFAULT '[]',
    match_json TEXT DEFAULT '[]',
    platform TEXT DEFAULT '',
    managed INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    source TEXT DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    action TEXT,
    detail TEXT,
    at TEXT
);

CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);

CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'send_sms',
    to_target TEXT DEFAULT '',
    body TEXT DEFAULT '',
    fire_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT,
    updated_at TEXT,
    google_event_id TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    error TEXT DEFAULT '',
    source TEXT DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS idx_calendar_fire_at ON calendar_events(fire_at);
CREATE INDEX IF NOT EXISTS idx_calendar_status ON calendar_events(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_name ON calendar_events(name);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def log_sync(self, source: str, action: str, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_log (source, action, detail, at) VALUES (?, ?, ?, ?)",
                (source, action, detail, _now_iso()),
            )
            conn.commit()

    @staticmethod
    def _row_to_contact(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "phone": row["phone"],
            "email": row["email"] or "",
            "notes": row["notes"] or "",
            "aliases": json.loads(row["aliases_json"] or "[]"),
            "match": json.loads(row["match_json"] or "[]"),
            "platform": row["platform"] or "",
            "managed": bool(row["managed"]),
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "source": row["source"] or "manual",
        }

    @staticmethod
    def _contact_to_row(contact: dict[str, Any]) -> tuple[Any, ...]:
        return (
            contact["id"],
            contact.get("name") or "",
            contact.get("phone") or "",
            contact.get("email") or "",
            contact.get("notes") or "",
            json.dumps(contact.get("aliases") or [], ensure_ascii=False),
            json.dumps(contact.get("match") or [], ensure_ascii=False),
            contact.get("platform") or "",
            1 if contact.get("managed", True) else 0,
            contact.get("created_at") or _now_iso(),
            contact.get("updated_at") or _now_iso(),
            contact.get("source") or "manual",
        )

    def all_contacts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM contacts ORDER BY lower(name)").fetchall()
        return [self._row_to_contact(r) for r in rows]

    def upsert_contact(self, contact: dict[str, Any]) -> None:
        row = self._contact_to_row(contact)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO contacts (
                    id, name, phone, email, notes, aliases_json, match_json,
                    platform, managed, created_at, updated_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    phone=excluded.phone,
                    email=excluded.email,
                    notes=excluded.notes,
                    aliases_json=excluded.aliases_json,
                    match_json=excluded.match_json,
                    platform=excluded.platform,
                    managed=excluded.managed,
                    updated_at=excluded.updated_at,
                    source=excluded.source
                """,
                row,
            )
            conn.commit()

    def delete_contact(self, contact_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
            conn.commit()
            return cur.rowcount > 0

    def replace_all_contacts(self, contacts: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM contacts")
            for c in contacts:
                conn.execute(
                    """
                    INSERT INTO contacts (
                        id, name, phone, email, notes, aliases_json, match_json,
                        platform, managed, created_at, updated_at, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._contact_to_row(c),
                )
            conn.commit()

    def kv_get(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, _now_iso()),
            )
            conn.commit()

    # --- calendar events ---

    @staticmethod
    def _row_to_calendar(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "title": row["title"] or "",
            "kind": row["kind"] or "send_sms",
            "to": row["to_target"] or "",
            "body": row["body"] or "",
            "fire_at": row["fire_at"] or "",
            "status": row["status"] or "pending",
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
            "google_event_id": row["google_event_id"] or "",
            "notes": row["notes"] or "",
            "error": row["error"] or "",
            "source": row["source"] or "local",
        }

    @staticmethod
    def _calendar_to_row(event: dict[str, Any]) -> tuple[Any, ...]:
        return (
            event["id"],
            event["name"],
            event.get("title") or "",
            event.get("kind") or "send_sms",
            event.get("to") or event.get("to_target") or "",
            event.get("body") or "",
            event["fire_at"],
            event.get("status") or "pending",
            event.get("created_at") or _now_iso(),
            event.get("updated_at") or _now_iso(),
            event.get("google_event_id") or "",
            event.get("notes") or "",
            event.get("error") or "",
            event.get("source") or "local",
        )

    def calendar_upsert(self, event: dict[str, Any]) -> None:
        row = self._calendar_to_row(event)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calendar_events (
                    id, name, title, kind, to_target, body, fire_at, status,
                    created_at, updated_at, google_event_id, notes, error, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    title=excluded.title,
                    kind=excluded.kind,
                    to_target=excluded.to_target,
                    body=excluded.body,
                    fire_at=excluded.fire_at,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    google_event_id=excluded.google_event_id,
                    notes=excluded.notes,
                    error=excluded.error,
                    source=excluded.source
                """,
                row,
            )
            conn.commit()

    def calendar_get(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
            ).fetchone()
        return self._row_to_calendar(row) if row else None

    def calendar_get_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_events WHERE lower(name) = lower(?)",
                (name.strip(),),
            ).fetchone()
        return self._row_to_calendar(row) if row else None

    def calendar_delete(self, event_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            conn.commit()
            return cur.rowcount > 0

    def calendar_list(
        self,
        *,
        status: str | None = None,
        pending_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if pending_only:
            clauses.append("status = 'pending'")
        elif status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        lim = f" LIMIT {int(limit)}" if limit else ""
        sql = f"SELECT * FROM calendar_events {where} ORDER BY fire_at ASC{lim}"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_calendar(r) for r in rows]

    def calendar_pending_due(self, *, before_iso: str | None = None) -> list[dict[str, Any]]:
        """Due events still waiting (read-only; scheduler uses calendar_claim_due)."""
        cutoff = before_iso or _now_iso()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM calendar_events
                WHERE status = 'pending' AND fire_at <= ?
                ORDER BY fire_at ASC
                """,
                (cutoff,),
            ).fetchall()
        return [self._row_to_calendar(r) for r in rows]

    def calendar_recover_stale_processing(self, *, max_age_seconds: int = 600) -> int:
        """Mark stuck in-flight events failed so they are never auto-retried."""
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        ).isoformat()
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE calendar_events
                SET status = 'failed',
                    error = CASE
                        WHEN trim(coalesce(error, '')) = ''
                        THEN 'interrupted during send — not retried automatically'
                        ELSE trim(error) || ' · interrupted — not retried automatically'
                    END,
                    updated_at = ?
                WHERE status = 'processing' AND updated_at < ?
                """,
                (now, stale_before),
            )
            conn.commit()
            return cur.rowcount

    def calendar_claim_due(self, *, before_iso: str | None = None) -> list[dict[str, Any]]:
        """Atomically move due pending events to processing (one worker per row)."""
        self.calendar_recover_stale_processing()
        cutoff = before_iso or _now_iso()
        now = _now_iso()
        claimed: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM calendar_events
                WHERE status = 'pending' AND fire_at <= ?
                ORDER BY fire_at ASC
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                eid = row["id"]
                cur = conn.execute(
                    """
                    UPDATE calendar_events
                    SET status = 'processing', updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now, eid),
                )
                if cur.rowcount:
                    full = conn.execute(
                        "SELECT * FROM calendar_events WHERE id = ?", (eid,)
                    ).fetchone()
                    if full:
                        claimed.append(self._row_to_calendar(full))
            conn.commit()
        return claimed

    def calendar_finalize(
        self,
        event_id: str,
        *,
        status: str,
        error: str = "",
    ) -> bool:
        """Set terminal status only from pending/processing (idempotent)."""
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE calendar_events
                SET status = ?, error = ?, updated_at = ?
                WHERE id = ? AND status IN ('pending', 'processing')
                """,
                (status, (error or "")[:500], now, event_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def calendar_count_pending(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM calendar_events WHERE status = 'pending'"
            ).fetchone()
        return int(row["n"]) if row else 0

    def calendar_update_status(
        self,
        event_id: str,
        *,
        status: str,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE calendar_events
                SET status = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, _now_iso(), event_id),
            )
            conn.commit()
