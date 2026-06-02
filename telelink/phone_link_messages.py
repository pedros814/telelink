"""Read SMS/MMS threads from Phone Link phone.db (Messages tab sync cache)."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telelink.contacts import dial_digits, looks_like_phone, normalize_phone
from telelink.harvest import _copy_query_db, _pkg_roots
from telelink.phone_link_calls import _filetime_to_iso

log = logging.getLogger(__name__)

_PHONE_DB_GLOBS = (
    "LocalCache/Indexed/*/System/Database/phone.db",
    "LocalCache/Indexed/*/System/Database/Phone.db",
    "LocalCache/Indexed/*/System/Database/messages.db",
    "LocalCache/Indexed/*/System/Database/Messages.db",
)

_PHONE_DB_NAMES = ("phone.db", "Phone.db", "messages.db", "Messages.db")
_CACHE_PREF = "phone_link_phone_db_path"

_MSG_TYPE_INCOMING = frozenset({1, "1", "received", "incoming", "in"})
_MSG_TYPE_OUTGOING = frozenset({2, "2", "sent", "outgoing", "out"})

_discovery_method: str = "none"


def get_phone_discovery_method() -> str:
    """``primary`` | ``fallback`` | ``none`` — set by last ``discover_phone_databases``."""
    return _discovery_method


def _discover_phone_primary() -> list[Path]:
    found: list[Path] = []
    for root in _pkg_roots():
        for pattern in _PHONE_DB_GLOBS:
            found.extend(root.glob(pattern))
    return list(dict.fromkeys(p for p in found if p.is_file()))


def _load_config_for_discovery(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is not None:
        return config
    try:
        from telelink.config import load_config

        return load_config()
    except Exception:
        return {}


def discover_phone_databases(
    config: dict[str, Any] | None = None,
) -> list[Path]:
    global _discovery_method

    found = _discover_phone_primary()
    used_fallback = False

    if not found:
        from telelink.phone_link_fallback import fallback_find_phone_databases

        extra = fallback_find_phone_databases(_load_config_for_discovery(config))
        if extra:
            used_fallback = True
            merged = list(dict.fromkeys(p.resolve() for p in found + extra if p.is_file()))
            found = merged

    _discovery_method = "fallback" if used_fallback else ("primary" if found else "none")
    return found


def _probe_message_rows(db_path: Path) -> int:
    try:
        work = _copy_query_db(db_path)
    except OSError:
        work = db_path
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
        tables = {
            r[0].lower()
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "message" in tables:
            return int(conn.execute("SELECT COUNT(*) FROM message").fetchone()[0])
        for name in tables:
            if "message" in name and name != "message_to_address":
                try:
                    return int(conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0])
                except sqlite3.Error:
                    continue
    except sqlite3.Error:
        return 0
    finally:
        if conn:
            conn.close()
    return 0


def _local_storage(config: dict[str, Any] | None) -> Any | None:
    if config is None:
        return None
    try:
        from telelink.session import get_session

        return get_session().local_storage
    except Exception:
        out = (config.get("output") or {}).get("localstorage_file")
        if not out:
            return None
        from telelink.local_storage import LocalStorage

        return LocalStorage(out)


def _sibling_phone_dbs(contacts_db: Path) -> list[Path]:
    """phone.db usually lives next to contacts.db once Messages sync runs."""
    if not contacts_db.is_file():
        return []
    folder = contacts_db.parent
    return [folder / name for name in _PHONE_DB_NAMES if (folder / name).is_file()]


def _pick_best_phone_db(candidates: list[Path]) -> Path | None:
    best: Path | None = None
    best_rows = -1
    best_mtime = 0.0
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        rows = _probe_message_rows(path)
        if rows > best_rows or (rows == best_rows and mtime > best_mtime):
            best_rows = rows
            best_mtime = mtime
            best = path
    return best


def describe_phone_db_status(
    config: dict[str, Any] | None = None,
    *,
    local_storage: Any | None = None,
) -> dict[str, Any]:
    """Diagnostics for config/doctor and convo empty-state hints."""
    from telelink.phone_link_contacts import resolve_contacts_db_path
    from telelink.phone_link_fallback import fallback_status

    ls = local_storage if local_storage is not None else _local_storage(config)
    contacts_db = resolve_contacts_db_path(config, local_storage=ls)
    expected_dir = str(contacts_db.parent.resolve()) if contacts_db else None
    discover_phone_databases(config)
    db = resolve_phone_db_path(config, local_storage=ls)
    rows = _probe_message_rows(db) if db else 0
    return {
        "found": bool(db),
        "path": str(db.resolve()) if db else None,
        "message_rows": rows,
        "expected_dir": expected_dir,
        "contacts_db": str(contacts_db.resolve()) if contacts_db else None,
        "discovery_method": get_phone_discovery_method(),
        "fallback": fallback_status(config),
    }


def resolve_phone_db_path(
    config: dict[str, Any] | None = None,
    *,
    local_storage: Any | None = None,
) -> Path | None:
    pl = (config or {}).get("phone_link") or {}
    raw = str(pl.get("phone_db") or pl.get("messages_db") or "").strip()
    if raw:
        from telelink.config import expand_path

        p = expand_path(raw)
        if p.is_file():
            return p.resolve()

    ls = local_storage if local_storage is not None else _local_storage(config)
    if ls:
        cached_raw = str(ls.pref(_CACHE_PREF) or "").strip()
        if cached_raw:
            try:
                cached = Path(cached_raw).resolve()
                if cached.is_file():
                    return cached
            except OSError:
                pass

    candidates: list[Path] = []
    from telelink.phone_link_contacts import resolve_contacts_db_path

    contacts_db = resolve_contacts_db_path(config, local_storage=ls)
    if contacts_db:
        candidates.extend(_sibling_phone_dbs(contacts_db))
    candidates.extend(discover_phone_databases(config))
    candidates = list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))

    best = _pick_best_phone_db(candidates)
    if best and ls:
        ls.set_pref(_CACHE_PREF, str(best.resolve()))
    return best


def _digits_key(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _message_direction(msg_type: Any) -> str:
    if msg_type in _MSG_TYPE_OUTGOING:
        return "out"
    if msg_type in _MSG_TYPE_INCOMING:
        return "in"
    try:
        n = int(msg_type)
        if n == 2:
            return "out"
        if n == 1:
            return "in"
    except (TypeError, ValueError):
        pass
    return "?"


def _row_timestamp_iso(row: dict[str, Any]) -> str:
    raw = row.get("timestamp") or row.get("date") or row.get("time")
    if raw is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.replace(microsecond=0).isoformat()
        except ValueError:
            pass
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    # Phone Link stores Windows FILETIME-ish ticks (100-ns since 1601)
    if n > 10_000_000_000:
        return _filetime_to_iso(n)
    # Unix ms
    if n > 1_000_000_000_000:
        dt = datetime.fromtimestamp(n / 1000.0, tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat()
    # Unix seconds
    if n > 1_000_000_000:
        dt = datetime.fromtimestamp(n, tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat()
    return _filetime_to_iso(n)


def _connect_readonly(db_path: Path) -> sqlite3.Connection | None:
    resolved = db_path.resolve()
    for uri in (
        f"file:{resolved}?mode=ro&immutable=1",
        f"file:{resolved}?mode=ro",
    ):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1")
            return conn
        except sqlite3.Error:
            continue
    try:
        work = _copy_query_db(resolved)
        conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except (OSError, sqlite3.Error):
        return None


def _read_messages_classic(
    conn: sqlite3.Connection,
    *,
    phone_keys: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """YPA / kacos2000 phone.db layout (message + message_to_address)."""
    keys = [k for k in phone_keys if len(k) >= 7]
    if not keys:
        return []
    clauses = []
    params: list[Any] = []
    for key in keys:
        like = f"%{key}%"
        clauses.append(
            "(REPLACE(REPLACE(IFNULL(m.from_address,''),'+',''),' ','') LIKE ? "
            "OR REPLACE(REPLACE(IFNULL(mta.address,''),'+',''),' ','') LIKE ?)"
        )
        params.extend([like, like])
    where = " OR ".join(clauses)
    sql = f"""
        SELECT
            m.message_id AS message_id,
            m.thread_id AS thread_id,
            m.timestamp AS timestamp,
            m.type AS msg_type,
            m.from_address AS from_address,
            m.body AS body,
            m.status AS status,
            mta.address AS to_address,
            c_from.display_name AS from_name,
            c_to.display_name AS to_name
        FROM message m
        LEFT JOIN message_to_address mta ON m.message_id = mta.message_id
        LEFT JOIN address a_from ON a_from.address = m.from_address
        LEFT JOIN contact c_from ON c_from.contact_id = a_from.contact_id
        LEFT JOIN address a_to ON a_to.address = mta.address
        LEFT JOIN contact c_to ON c_to.contact_id = a_to.contact_id
        WHERE ({where})
        GROUP BY m.message_id
        ORDER BY m.timestamp DESC
        LIMIT ?
    """
    params.append(max(1, limit))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        log.debug("classic message query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        rd = dict(row)
        direction = _message_direction(rd.get("msg_type"))
        from_addr = str(rd.get("from_address") or "").strip()
        to_addr = str(rd.get("to_address") or "").strip()
        body = str(rd.get("body") or "").strip()
        peer = to_addr if direction == "out" else from_addr
        peer_name = (
            str(rd.get("to_name") or "").strip()
            if direction == "out"
            else str(rd.get("from_name") or "").strip()
        )
        out.append(
            {
                "id": f"plink-msg-{rd.get('message_id')}",
                "direction": direction,
                "body": body,
                "from_address": from_addr,
                "to_address": to_addr,
                "peer": peer,
                "peer_name": peer_name,
                "timestamp": _row_timestamp_iso(rd),
                "thread_id": rd.get("thread_id"),
                "status": rd.get("status"),
                "source": "phone_link_db",
            }
        )
    return out


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info([{table}])")]
    except sqlite3.Error:
        return []


def _pick_col(cols: list[str], *candidates: str) -> str | None:
    lower = {c.lower(): c for c in cols}
    for want in candidates:
        if want.lower() in lower:
            return lower[want.lower()]
    return None


def _read_messages_generic(
    conn: sqlite3.Connection,
    *,
    phone_keys: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    msg_table = None
    for name in tables:
        if name.lower() == "message":
            msg_table = name
            break
    if not msg_table:
        for name in tables:
            if "message" in name.lower() and "address" not in name.lower():
                msg_table = name
                break
    if not msg_table:
        return []

    cols = _table_columns(conn, msg_table)
    body_col = _pick_col(cols, "body", "text", "content", "message")
    ts_col = _pick_col(cols, "timestamp", "date", "time", "sent_time", "last_updated_time")
    type_col = _pick_col(cols, "type", "direction", "msg_type")
    from_col = _pick_col(cols, "from_address", "from", "sender", "address")
    id_col = _pick_col(cols, "message_id", "id", "rowid")
    if not body_col and not from_col:
        return []

    sel = [c for c in (id_col, ts_col, type_col, from_col, body_col) if c]
    try:
        cur = conn.execute(
            f"SELECT {', '.join(f'[{c}]' for c in sel)} FROM [{msg_table}] "
            f"ORDER BY [{ts_col or id_col or sel[0]}] DESC LIMIT ?",
            (max(limit * 4, 200),),
        )
        raw_rows = cur.fetchall()
        names = [d[0] for d in (cur.description or [])]
    except sqlite3.Error as exc:
        log.debug("generic message read failed: %s", exc)
        return []

    keys = [k for k in phone_keys if len(k) >= 7]
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        rd = dict(zip(names, row))
        from_addr = str(rd.get(from_col or "") or "").strip() if from_col else ""
        body = str(rd.get(body_col or "") or "").strip() if body_col else ""
        if keys:
            hay = _digits_key(from_addr + body)
            if not any(k in hay for k in keys):
                continue
        direction = _message_direction(rd.get(type_col)) if type_col else "?"
        ts_row = {ts_col: rd.get(ts_col)} if ts_col else {}
        out.append(
            {
                "id": f"plink-msg-{rd.get(id_col) if id_col else len(out)}",
                "direction": direction,
                "body": body,
                "from_address": from_addr,
                "to_address": "",
                "peer": from_addr,
                "peer_name": "",
                "timestamp": _row_timestamp_iso(ts_row),
                "thread_id": None,
                "status": None,
                "source": "phone_link_db",
            }
        )
        if len(out) >= limit:
            break
    return out


def read_conversation_messages(
    db_path: Path,
    *,
    phone_keys: set[str],
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = _connect_readonly(db_path)
    if not conn:
        return []
    try:
        rows = _read_messages_classic(conn, phone_keys=phone_keys, limit=limit)
        if not rows:
            rows = _read_messages_generic(conn, phone_keys=phone_keys, limit=limit)
    finally:
        conn.close()
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return rows[:limit]


def phone_keys_for_target(
    target: str,
    *,
    config: dict[str, Any],
    contact_store: Any,
) -> tuple[set[str], str, str]:
    """
    Resolve CLI target to digit keys, display label, and E.164 phone.
    Returns (keys, display, phone).
    """
    from telelink.messaging import resolve_send_recipient

    raw = (target or "").strip()
    if not raw:
        raise ValueError("missing contact name or phone number — e.g. convo mom")

    if looks_like_phone(raw):
        phone = normalize_phone(raw)
        keys = {_digits_key(phone)}
        if len(_digits_key(phone)) == 11 and _digits_key(phone).startswith("1"):
            keys.add(_digits_key(phone)[1:])
        return keys, phone, phone

    phone, display = resolve_send_recipient(raw, store=contact_store)
    keys = {_digits_key(phone)}
    dial = dial_digits(phone)
    if dial:
        keys.add(dial)
    if len(dial) == 11 and dial.startswith("1"):
        keys.add(dial[1:])
    for token in re.split(r"[\s,]+", raw.lower()):
        if len(token) >= 2:
            keys.add(_digits_key(token))
    return keys, display, phone


def list_conversation_threads(
    db_path: Path,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Recent threads (peer address + optional name) for convo threads."""
    conn = _connect_readonly(db_path)
    if not conn:
        return []
    try:
        sql = """
            SELECT
                COALESCE(m.from_address, mta.address) AS peer_address,
                MAX(c.display_name) AS peer_name,
                MAX(m.timestamp) AS last_ts,
                COUNT(*) AS msg_count
            FROM message m
            LEFT JOIN message_to_address mta ON m.message_id = mta.message_id
            LEFT JOIN address a ON a.address = COALESCE(m.from_address, mta.address)
            LEFT JOIN contact c ON c.contact_id = a.contact_id
            WHERE COALESCE(m.from_address, mta.address) IS NOT NULL
              AND TRIM(COALESCE(m.from_address, mta.address)) != ''
            GROUP BY COALESCE(m.from_address, mta.address)
            ORDER BY last_ts DESC
            LIMIT ?
        """
        try:
            rows = conn.execute(sql, (max(1, limit),)).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        rd = dict(row)
        addr = str(rd.get("peer_address") or "").strip()
        out.append(
            {
                "peer": addr,
                "peer_name": str(rd.get("peer_name") or "").strip(),
                "phone": normalize_phone(addr) if looks_like_phone(addr) else "",
                "timestamp": _row_timestamp_iso({"timestamp": rd.get("last_ts")}),
                "msg_count": int(rd.get("msg_count") or 0),
            }
        )
    return out
