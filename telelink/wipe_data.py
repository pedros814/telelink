"""Clear local TeleLink data stores (caught, contacts, attachments, etc.)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telelink.analyze_snapshot import analyze_dir
from telelink.sent_log import sent_log_path

# Canonical wipe targets (order matters for wipe all).
ALL_TARGETS: tuple[str, ...] = (
    "caught",
    "calls",
    "sent",
    "contacts",
    "localstorage",
    "attachments",
    "analyze",
    "seen",
    "calendar",
    "db",
)

_TARGET_ALIASES: dict[str, str] = {
    "all": "all",
    "everything": "all",
    "tasks": "caught",
    "task": "caught",
    "notifications": "caught",
    "notification": "caught",
    "call": "calls",
    "call-log": "calls",
    "calllog": "calls",
    "missed": "calls",
    "messages": "caught",
    "sent-log": "sent",
    "sentlog": "sent",
    "sms-log": "sent",
    "contact": "contacts",
    "people": "contacts",
    "localstore": "localstorage",
    "local-store": "localstorage",
    "storage": "localstorage",
    "ls": "localstorage",
    "attachment": "attachments",
    "files": "attachments",
    "media": "attachments",
    "analyze-snapshot": "analyze",
    "snapshots": "analyze",
    "notif-seen": "seen",
    "notif_seen": "seen",
    "notifications-seen": "seen",
    "seen-notifications": "seen",
    "sqlite": "db",
    "database": "db",
    "telelink.db": "db",
    "schedule": "calendar",
    "scheduled": "calendar",
    "events": "calendar",
}


@dataclass
class WipeReport:
    cleared: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.cleared)


def wipe_target_names() -> list[str]:
    return ["all", *ALL_TARGETS]


def resolve_wipe_targets(parts: list[str]) -> list[str] | None:
    """Parse wipe args into canonical target names. None if empty/unknown."""
    if not parts:
        return None
    tokens: list[str] = []
    for part in parts:
        for piece in part.replace(",", " ").split():
            piece = piece.strip().lower()
            if piece:
                tokens.append(piece)
    if not tokens:
        return None

    resolved: list[str] = []
    for token in tokens:
        key = _TARGET_ALIASES.get(token, token)
        if key == "all":
            return list(ALL_TARGETS)
        if key not in ALL_TARGETS:
            return None
        if key not in resolved:
            resolved.append(key)
    return resolved or None


def _truncate_file(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return True


def _clear_directory(path: Path) -> int:
    if not path.exists():
        return 0
    removed = 0
    for child in list(path.iterdir()):
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _paths_from_config(config: dict[str, Any]) -> dict[str, Path]:
    out = config.get("output") or {}
    base = Path(out.get("dir", "./data"))
    return {
        "caught": Path(out.get("caught_file", base / "caught.jsonl")),
        "contacts": Path(out.get("contacts_file", base / "contacts.jsonl")),
        "sqlite": Path(out.get("sqlite_file", base / "telelink.db")),
        "localstorage": Path(out.get("localstorage_file", base / "localstorage.json")),
        "attachments": Path(out.get("attachments_dir", base / "attachments")),
        "seen": base / "notif-seen.txt",
        "sent": sent_log_path(config),
        "analyze": analyze_dir(config),
        "calls": Path(out.get("calls_file", base / "calls.jsonl")),
    }


def wipe_targets(
    config: dict[str, Any],
    targets: list[str],
    *,
    session: Any | None = None,
) -> WipeReport:
    """Clear selected data. config.yaml is never modified."""
    report = WipeReport()
    paths = _paths_from_config(config)

    if "all" in targets:
        targets = list(ALL_TARGETS)

    for target in targets:
        try:
            if target == "caught":
                _truncate_file(paths["caught"])
                _truncate_file(paths["seen"])
                if session is not None:
                    session.caught_store._seen_ids.clear()
                report.cleared.append(f"caught → {paths['caught']}")
                report.cleared.append(f"seen → {paths['seen']} (reset dedup for re-capture)")
            elif target == "sent":
                _truncate_file(paths["sent"])
                report.cleared.append(f"sent → {paths['sent']}")
            elif target == "calls":
                _truncate_file(paths["calls"])
                if session is not None:
                    session.call_log_store._seen.clear()
                report.cleared.append(f"calls → {paths['calls']}")
            elif target == "contacts":
                if session is not None:
                    session.contact_store._by_id.clear()
                    session.contact_store._persist_jsonl_only()
                    if session.contact_store.db:
                        session.contact_store.db.replace_all_contacts([])
                    if session.contact_store.local_storage:
                        session.contact_store.local_storage.clear_pending_contacts()
                else:
                    _truncate_file(paths["contacts"])
                report.cleared.append(f"contacts → {paths['contacts']}")
            elif target == "localstorage":
                if session is not None:
                    session.local_storage.reset()
                else:
                    from telelink.local_storage import LocalStorage

                    LocalStorage(paths["localstorage"]).reset()
                report.cleared.append(f"localstorage → {paths['localstorage']}")
            elif target == "attachments":
                n = _clear_directory(paths["attachments"])
                paths["attachments"].mkdir(parents=True, exist_ok=True)
                report.cleared.append(f"attachments → {paths['attachments']} ({n} item(s))")
            elif target == "analyze":
                n = _clear_directory(paths["analyze"])
                paths["analyze"].mkdir(parents=True, exist_ok=True)
                report.cleared.append(f"analyze → {paths['analyze']} ({n} item(s))")
            elif target == "seen":
                _truncate_file(paths["seen"])
                report.cleared.append(f"seen → {paths['seen']}")
            elif target == "calendar":
                if session is not None and session.db:
                    with session.db._connect() as conn:
                        conn.execute("DELETE FROM calendar_events")
                        conn.commit()
                else:
                    from telelink.db import Database

                    with Database(paths["sqlite"])._connect() as conn:
                        conn.execute("DELETE FROM calendar_events")
                        conn.commit()
                report.cleared.append("calendar → scheduled events cleared")
            elif target == "db":
                db_path = paths["sqlite"]
                if db_path.exists():
                    try:
                        db_path.unlink()
                    except OSError:
                        if session is not None and session.db:
                            from telelink.db import Database

                            with session.db._connect() as conn:
                                conn.executescript(
                                    "DELETE FROM contacts; DELETE FROM kv; DELETE FROM sync_log; DELETE FROM calendar_events;"
                                )
                                conn.commit()
                        else:
                            raise
                if session is not None:
                    from telelink.db import Database

                    session.db = Database(db_path)
                report.cleared.append(f"db → {db_path}")
            else:
                report.skipped.append(target)
        except OSError as exc:
            report.skipped.append(f"{target} ({exc})")

    if session is not None:
        session.cache.invalidate()
    return report
