"""Import call history from Phone Link calling.db (same data as the Calls UI)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telelink.classify import normalize_sender_id, resolve_contact
from telelink.call_log import CallEntry, CallLogStore, call_log_enabled, call_log_ttl_seconds
from telelink.contacts import normalize_phone
from telelink.harvest import _copy_query_db, _pkg_roots
from telelink.phone_link_contacts import lookup_phone_link_contact

log = logging.getLogger(__name__)

_CALLING_DB_GLOB = "LocalCache/Indexed/*/System/Database/calling.db"

# Android CallLog.Calls — matches Phone Link calling.db call_type values.
_CALL_TYPE_KIND: dict[int, str] = {
    1: "incoming",
    2: "outgoing",
    3: "missed",
    4: "voicemail",
    5: "declined",
    6: "blocked",
    7: "answered_externally",
}

_discovery_method: str = "none"


def get_calling_discovery_method() -> str:
    """``primary`` | ``fallback`` | ``none`` — set by last ``discover_calling_databases``."""
    return _discovery_method


def _discover_calling_primary() -> list[Path]:
    found: list[Path] = []
    for root in _pkg_roots():
        found.extend(root.glob(_CALLING_DB_GLOB))
    return list(dict.fromkeys(p for p in found if p.is_file()))


def _load_config_for_discovery(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is not None:
        return config
    try:
        from telelink.config import load_config

        return load_config()
    except Exception:
        return {}


def discover_calling_databases(
    *,
    probe: bool = True,
    config: dict[str, Any] | None = None,
) -> list[Path]:
    global _discovery_method

    found = _discover_calling_primary()
    used_fallback = False

    if not found:
        from telelink.phone_link_fallback import fallback_find_calling_databases

        extra = fallback_find_calling_databases(_load_config_for_discovery(config))
        if extra:
            used_fallback = True
            found = list(dict.fromkeys(p.resolve() for p in found + extra if p.is_file()))

    _discovery_method = "fallback" if used_fallback else ("primary" if found else "none")
    return found


def _filetime_to_iso(ft: int | float | None) -> str:
    if not ft:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        ticks = int(ft)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    dt = epoch + timedelta(microseconds=ticks / 10)
    return dt.replace(microsecond=0).isoformat()


def _best_calling_db(candidates: list[Path], *, probe: bool = True) -> Path | None:
    best: Path | None = None
    best_rows = -1
    best_mtime = 0.0
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        rows = 0
        if probe:
            try:
                work = _copy_query_db(path)
                conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
                rows = conn.execute("SELECT COUNT(*) FROM call_history").fetchone()[0]
                conn.close()
            except Exception:
                rows = 0
        if rows > best_rows or (rows == best_rows and mtime > best_mtime):
            best_rows = rows
            best_mtime = mtime
            best = path
    return best


def resolve_calling_db_path(config: dict[str, Any] | None = None) -> Path | None:
    pl = (config or {}).get("phone_link") or {}
    raw = str(pl.get("calling_db") or "").strip()
    if raw:
        from telelink.config import expand_path

        p = expand_path(raw)
        if p.is_file():
            return p
    candidates = discover_calling_databases(config=config)
    return _best_calling_db(candidates, probe=True)


def _kind_from_call_type(call_type: int) -> str:
    return _CALL_TYPE_KIND.get(int(call_type), "unknown")


def _format_body(kind: str, phone: str, duration_sec: int) -> str:
    label = kind.replace("_", " ")
    dur = f"{duration_sec}s" if duration_sec else "0s"
    return f"{label} - {phone} - {dur}"


def read_call_history(
    db_path: Path,
    *,
    limit: int = 200,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rows from call_history table."""
    try:
        work = _copy_query_db(db_path)
    except OSError:
        work = db_path
    conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT call_id, phone_number, duration, call_type, start_time, is_read "
            "FROM call_history ORDER BY start_time DESC LIMIT ?"
        )
        rows = conn.execute(sql, (max(1, limit),)).fetchall()
    except sqlite3.Error as exc:
        log.debug("call_history read failed: %s", exc)
        return []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        ts = _filetime_to_iso(row["start_time"])
        if since:
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < since:
                    continue
            except ValueError:
                pass
        out.append(dict(row))
    return out


def rows_to_call_entries(
    rows: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    contact_store: Any | None = None,
) -> list[CallEntry]:
    entries: list[CallEntry] = []
    for row in rows:
        phone_raw = str(row.get("phone_number") or "").strip()
        phone = normalize_phone(phone_raw) if phone_raw else phone_raw
        call_id = row.get("call_id")
        kind = _kind_from_call_type(int(row.get("call_type") or 0))
        duration = int(row.get("duration") or 0)

        display = phone
        pl_name = lookup_phone_link_contact(phone, "", config=config)
        if pl_name:
            display = pl_name

        contact, matched = resolve_contact(config, display, phone, store=contact_store)
        if pl_name and not matched:
            contact = pl_name

        stable_id = f"plink-{call_id}" if call_id is not None else None
        entry = CallEntry(
            id=stable_id or CallEntry().id,
            kind=kind,
            caller=display or phone or "unknown",
            sender_id=normalize_sender_id(phone or display),
            contact=contact,
            contact_matched=matched,
            body=_format_body(kind, phone or display, duration),
            notification_app="Phone Link",
            source="phone_link_db",
            timestamp=_filetime_to_iso(row.get("start_time")),
        )
        entries.append(entry)
    return entries


def sync_calls_from_phone_link(
    config: dict[str, Any],
    store: CallLogStore,
    *,
    contact_store: Any | None = None,
    limit: int | None = None,
) -> int:
    """
    Import call_history from Phone Link calling.db into calls.jsonl.
    Returns number of newly added rows.
    """
    if not call_log_enabled(config):
        return 0

    calls_cfg = config.get("calls") or {}
    if calls_cfg.get("sync_phone_link_db", True) is False:
        return 0

    db_path = resolve_calling_db_path(config)
    if not db_path:
        log.debug("calling.db not found")
        return 0

    max_rows = limit if limit is not None else int(calls_cfg.get("sync_limit") or 200)

    rows = read_call_history(db_path, limit=max_rows)
    entries = rows_to_call_entries(rows, config=config, contact_store=contact_store)
    return store.upsert_entries(entries)

