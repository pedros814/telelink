"""Startup sync: config.yaml + contacts.jsonl + localStorage + SQLite + Phone Link DB."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from telelink.contacts import ContactStore
    from telelink.db import Database
    from telelink.local_storage import LocalStorage


def _parse_ts(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _newer(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Pick row with later updated_at (or a if b missing)."""
    if not b:
        return a
    if not a:
        return b
    return a if _parse_ts(str(a.get("updated_at") or "")) >= _parse_ts(str(b.get("updated_at") or "")) else b


def _merge_key(row: dict[str, Any]) -> str:
    phone = str(row.get("phone") or "").strip()
    if phone:
        return f"phone:{phone}"
    return f"name:{(row.get('name') or '').lower()}"


@dataclass
class SyncReport:
    from_config: int = 0
    from_jsonl: int = 0
    from_localstorage: int = 0
    from_phone_link: int = 0
    from_caught: int = 0
    total: int = 0


@dataclass
class FullSyncReport(SyncReport):
    phone_link_db_path: str | None = None
    phone_link_contacts_db: int = 0
    phone_link_message_dbs: int = 0
    watch_folders: int = 0
    calls_imported: int = 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def merge_contact_sources(
    *,
    config: dict[str, Any],
    jsonl_path: Path,
    local_storage: "LocalStorage | None",
    db: "Database | None",
    import_phone_link: bool = True,
    import_tasks: bool = False,
    task_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], SyncReport]:
    """Merge all contact sources into a dict keyed by merge key."""
    from telelink.contacts import _repair_contact_row

    merged: dict[str, dict[str, Any]] = {}
    report = SyncReport()

    def absorb(row: dict[str, Any], source: str) -> None:
        row = _repair_contact_row(dict(row))
        if not row.get("id"):
            return
        row["source"] = source
        key = _merge_key(row)
        merged[key] = _newer(row, merged.get(key, {}))

    # JSONL (human-editable export) — load before SQLite so empty DB cannot win
    for row in _load_jsonl(jsonl_path):
        absorb(row, "jsonl")
        report.from_jsonl += 1

    # SQLite canonical store
    if db:
        for row in db.all_contacts():
            absorb(row, str(row.get("source") or "sqlite"))

    # config.yaml legacy list
    entries = config.get("contacts") or config.get("clients") or []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        patterns = [str(p).strip() for p in (entry.get("match") or []) if str(p).strip()]
        phone = ""
        text_pats: list[str] = []
        for pat in patterns:
            from telelink.contacts import looks_like_phone, normalize_phone

            if looks_like_phone(pat):
                if not phone:
                    phone = normalize_phone(pat)
            else:
                text_pats.append(pat)
        if not phone:
            continue
        import re
        import uuid

        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "phone": phone,
            "email": "",
            "notes": "",
            "aliases": [],
            "match": list(
                dict.fromkeys(text_pats + [name.lower(), phone, re.sub(r"\D", "", phone)])
            ),
            "platform": str(entry.get("platform") or ""),
            "managed": bool(entry.get("managed", True)),
            "created_at": now,
            "updated_at": now,
        }
        absorb(row, "config")
        report.from_config += 1

    # localStorage — pending rows only (not a contact store; canonical = jsonl + sqlite)
    if local_storage:
        for row in local_storage.pending_contacts():
            absorb(row, "localstorage_pending")
            report.from_localstorage += 1

    # Phone Link SQLite hints (suggestions, managed=false)
    if import_phone_link:
        from telelink.phone_link_sqlite import import_phone_link_contacts

        for row in import_phone_link_contacts(config=config):
            absorb(row, row.get("source") or "phone_link")
            report.from_phone_link += 1

    # Optional task senders
    if import_tasks and task_rows:
        from telelink.contacts import looks_like_phone, normalize_phone
        import uuid

        now = datetime.now(timezone.utc).isoformat()
        for task in reversed(task_rows):
            sender = str(task.get("sender") or "").strip()
            sid = str(task.get("sender_id") or "").strip()
            phone_raw = sender if looks_like_phone(sender) else sid if looks_like_phone(sid) else ""
            if not phone_raw:
                continue
            phone = normalize_phone(phone_raw)
            key = f"phone:{phone}"
            if key in merged:
                continue
            name = sender if not looks_like_phone(sender) else phone
            row = {
                "id": str(uuid.uuid4()),
                "name": name[:60],
                "phone": phone,
                "email": "",
                "notes": "imported from tasks",
                "aliases": [],
                "match": [name.lower(), phone],
                "platform": "",
                "managed": False,
                "created_at": now,
                "updated_at": now,
            }
            absorb(row, "caught")
            report.from_caught += 1

    report.total = len(merged)
    return merged, report


def apply_merged_contacts(
    merged: dict[str, dict[str, Any]],
    *,
    db: "Database | None",
    jsonl_path: Path,
    local_storage: "LocalStorage | None",
) -> None:
    if not merged and jsonl_path.exists() and jsonl_path.stat().st_size > 2:
        return
    by_id: dict[str, dict[str, Any]] = {}
    for row in merged.values():
        cid = row["id"]
        by_id[cid] = _newer(row, by_id.get(cid, {}))
    rows = sorted(by_id.values(), key=lambda r: (r.get("name") or "").lower())
    if db:
        db.replace_all_contacts(rows)
        db.log_sync("bootstrap", "contacts", f"{len(rows)} rows")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if local_storage:
        local_storage.mark_synced_many("jsonl", "sqlite", "config")
        local_storage.clear_pending_contacts()


def bootstrap_contacts(
    config: dict[str, Any],
    contact_store: "ContactStore",
    *,
    db: "Database | None" = None,
    local_storage: "LocalStorage | None" = None,
    import_phone_link: bool = True,
    import_caught: bool = False,
    import_tasks: bool | None = None,
    task_rows: list[dict[str, Any]] | None = None,
) -> SyncReport:
    """Full startup sync into store + sqlite + jsonl."""
    sync_cfg = config.get("sync", {})
    if import_tasks is not None:
        import_caught = import_tasks
    do_caught = import_caught or sync_cfg.get(
        "import_caught_on_startup", sync_cfg.get("import_tasks_on_startup", False)
    )
    merged, report = merge_contact_sources(
        config=config,
        jsonl_path=Path(config["output"]["contacts_file"]),
        local_storage=local_storage,
        db=db,
        import_phone_link=import_phone_link and sync_cfg.get("import_phone_link_db", True),
        import_tasks=do_caught,
        task_rows=task_rows,
    )
    apply_merged_contacts(
        merged,
        db=db,
        jsonl_path=Path(config["output"]["contacts_file"]),
        local_storage=local_storage,
    )
    contact_store.reload_from_disk()
    return report


def _refresh_phone_link_sources(
    config: dict[str, Any],
    local_storage: "LocalStorage | None",
    *,
    force: bool = True,
) -> tuple[int, int, str | None]:
    """Re-discover Phone Link DBs and reload contacts.db index. Returns (plink_rows, msg_dbs, path)."""
    from telelink.harvest import find_phone_link_databases
    from telelink.phone_link_contacts import (
        clear_phone_link_contact_cache,
        discover_contacts_databases,
        get_phone_link_contact_index,
        resolve_contacts_db_path,
    )

    clear_phone_link_contact_cache()
    candidates = discover_contacts_databases(probe=True, config=config)
    db_path = resolve_contacts_db_path(
        config,
        local_storage=local_storage,
        candidates=candidates,
        force=force,
    )
    idx = get_phone_link_contact_index(config, local_storage=local_storage)
    pl_count = idx.load(config, force=True, local_storage=local_storage)
    msg_dbs = len(find_phone_link_databases())
    return pl_count, msg_dbs, str(db_path) if db_path else None


def run_full_sync(
    session: Any,
    *,
    import_caught: bool = False,
    force: bool = True,
    quiet: bool = False,
) -> FullSyncReport:
    """
    Re-sync TeleLink from Phone Link and all contact sources.

    Clears stale in-memory caches, re-discovers contacts.db, merges jsonl/sqlite/config,
    and refreshes contact resolution caches.
    """
    session.reload_config()
    config = session.config
    sync_cfg = config.get("sync", {})
    ls = session.local_storage

    pl_count, msg_dbs, pl_path = _refresh_phone_link_sources(
        config, ls, force=force or sync_cfg.get("import_phone_link_db", True)
    )
    session.cache.invalidate()

    task_rows = None
    if import_caught:
        task_rows = session.caught_store.list_caught()

    report = bootstrap_contacts(
        config,
        session.contact_store,
        db=session.db,
        local_storage=ls,
        import_phone_link=sync_cfg.get("import_phone_link_db", True),
        import_caught=import_caught,
        task_rows=task_rows,
    )
    session.on_contacts_changed()
    ls.mark_synced_many("phone_link", "full")

    calls_added = 0
    if (config.get("calls") or {}).get("enabled", True) is not False:
        from telelink.phone_link_calls import sync_calls_from_phone_link

        calls_added = sync_calls_from_phone_link(
            config,
            session.call_log_store,
            contact_store=session.contact_store,
        )

    watch = (config.get("phone_link") or {}).get("watch_folders") or []
    full = FullSyncReport(
        from_config=report.from_config,
        from_jsonl=report.from_jsonl,
        from_localstorage=report.from_localstorage,
        from_phone_link=report.from_phone_link,
        from_caught=report.from_caught,
        total=report.total,
        phone_link_db_path=pl_path,
        phone_link_contacts_db=pl_count,
        phone_link_message_dbs=msg_dbs,
        watch_folders=len(watch),
        calls_imported=calls_added,
    )
    session.sync_report = full
    if not quiet:
        from telelink import pretty

        parts = [
            f"{full.total} contacts",
            f"config {full.from_config}",
            f"jsonl {full.from_jsonl}",
            f"plink {full.from_phone_link}",
        ]
        if full.from_caught:
            parts.append(f"caught {full.from_caught}")
        detail = f"Phone Link DB: {pl_count} rows"
        if pl_path:
            detail += f" ({pl_path})"
        else:
            detail += " — open Phone Link and sync contacts from iPhone"
        pretty.info("SYNC", ", ".join(parts))
        pretty.info("SYNC", detail)
        if calls_added:
            pretty.info("SYNC", f"{calls_added} call(s) imported from Phone Link calling.db")
    return full


def format_sync_summary(report: SyncReport | FullSyncReport) -> str:
    """One-line summary for config/status output."""
    base = (
        f"{report.total} contacts "
        f"(config {report.from_config}, jsonl {report.from_jsonl}, "
        f"plink {report.from_phone_link}"
    )
    if report.from_caught:
        base += f", caught {report.from_caught}"
    base += ")"
    if isinstance(report, FullSyncReport) and report.phone_link_db_path:
        base += f" — {report.phone_link_contacts_db} in Phone Link DB"
    return base
