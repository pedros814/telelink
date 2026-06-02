"""Import contact hints from Phone Link SQLite message/photo databases."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from telelink.contacts import looks_like_phone, normalize_phone
from telelink.harvest import _copy_query_db, find_phone_link_databases
from telelink.phone_link_contacts import import_phone_link_contacts_from_db

_PHONE_COLS = frozenset(
    {
        "phone",
        "number",
        "address",
        "from_address",
        "to_address",
        "sender",
        "recipient",
        "participant",
        "display_name",
        "name",
        "title",
        "conversation_name",
    }
)


def _scan_db(db_path: Path) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    try:
        work = _copy_query_db(db_path)
    except OSError:
        work = db_path
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
    except sqlite3.Error:
        return hints
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{table}])")]
            except sqlite3.Error:
                continue
            interesting = [c for c in cols if c.lower() in _PHONE_COLS]
            if not interesting:
                continue
            try:
                cur = conn.execute(f"SELECT * FROM [{table}] LIMIT 300")
                names = [d[0] for d in (cur.description or [])]
                rows = cur.fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                data = dict(zip(names, row))
                phone = ""
                label = ""
                for col in interesting:
                    val = str(data.get(col) or "").strip()
                    if not val:
                        continue
                    if looks_like_phone(val):
                        phone = normalize_phone(val)
                    elif len(val) >= 2 and not label:
                        label = val[:80]
                if phone:
                    hints.append(
                        {
                            "name": label or phone,
                            "phone": phone,
                            "match": [label.lower(), phone, re.sub(r"\D", "", phone)]
                            if label
                            else [phone, re.sub(r"\D", "", phone)],
                            "managed": False,
                            "source": f"phone_link:{db_path.name}",
                            "notes": f"from {table}",
                        }
                    )
    finally:
        if conn:
            conn.close()
    return hints


def import_phone_link_contacts(
    *,
    limit: int = 40,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Collect deduped contact hints from Phone Link (contacts.db first, then message DBs)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in import_phone_link_contacts_from_db(limit=limit, config=config):
        phone = row.get("phone") or ""
        if phone and phone not in seen:
            seen.add(phone)
            out.append(row)
    if len(out) >= limit:
        return out[:limit]

    for db in find_phone_link_databases():
        for hint in _scan_db(db):
            phone = hint.get("phone") or ""
            if not phone or phone in seen:
                continue
            seen.add(phone)
            out.append(hint)
            if len(out) >= limit:
                return out
    return out
