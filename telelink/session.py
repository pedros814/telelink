"""TeleLink session — config, DB, localStorage, caches, live reload."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from telelink.cache import TTLCache
from telelink.config import DEFAULT_CONFIG_NAME, load_config
from telelink.contacts import ContactStore
from telelink.db import Database
from telelink.local_storage import LocalStorage
from telelink.call_log import CallLogStore
from telelink.store import CaughtStore
from telelink.sync import FullSyncReport, SyncReport, bootstrap_contacts

_session: "TeleLinkSession | None" = None


class TeleLinkSession:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        config_path: Path,
        db: Database,
        local_storage: LocalStorage,
        contact_store: ContactStore,
        caught_store: CaughtStore,
        call_log_store: CallLogStore,
        sync_report: SyncReport | None = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.db = db
        self.local_storage = local_storage
        self.contact_store = contact_store
        self.caught_store = caught_store
        self.call_log_store = call_log_store
        self.task_store = caught_store
        self.sync_report = sync_report
        self._config_mtime: float = 0.0
        self.cache = TTLCache(ttl_seconds=float(config.get("cache", {}).get("ttl_seconds", 30)))
        self._touch_config_mtime()

    def _touch_config_mtime(self) -> None:
        if self.config_path.exists():
            self._config_mtime = self.config_path.stat().st_mtime

    def config_fresh(self) -> dict[str, Any]:
        """Return config, reloading from disk if config.yaml changed."""
        if self.config_path.exists():
            mtime = self.config_path.stat().st_mtime
            if mtime > self._config_mtime:
                self.reload_config()
        return self.config

    def reload_config(self) -> dict[str, Any]:
        self.config = load_config(self.config_path)
        self._touch_config_mtime()
        self.cache.invalidate()
        return self.config

    def on_contacts_changed(self) -> None:
        """After add/remove/upsert — refresh in-memory cache (sqlite/jsonl written in _persist)."""
        self.local_storage.mark_synced("jsonl")
        self.cache.invalidate("contacts")
        self.cache.invalidate("resolve")

    def invalidate_resolve_cache(self) -> None:
        self.cache.invalidate("resolve")

    @classmethod
    def bootstrap(cls, config_path: Path | None = None) -> "TeleLinkSession":
        path = config_path or Path.cwd() / DEFAULT_CONFIG_NAME
        config = load_config(path)
        out = config["output"]

        db = Database(out["sqlite_file"])
        ls = LocalStorage(out["localstorage_file"])
        contact_store = ContactStore(
            out["contacts_file"],
            db=db,
            local_storage=ls,
        )
        sync_cfg = config.get("sync", {})
        report = None
        caught_store = CaughtStore(out["caught_file"], out["attachments_dir"])
        from telelink.startup_sync import should_defer_startup_sync

        if sync_cfg.get("on_startup", True) and not should_defer_startup_sync(config):
            from telelink.sync import FullSyncReport, _refresh_phone_link_sources, bootstrap_contacts

            pl_count, msg_dbs, pl_path = _refresh_phone_link_sources(config, ls, force=True)
            task_rows = None
            if sync_cfg.get(
                "import_caught_on_startup", sync_cfg.get("import_tasks_on_startup", False)
            ):
                task_rows = caught_store.list_caught()
            boot = bootstrap_contacts(
                config,
                contact_store,
                db=db,
                local_storage=ls,
                import_phone_link=sync_cfg.get("import_phone_link_db", True),
                import_caught=bool(task_rows),
                task_rows=task_rows,
            )
            ls.mark_synced_many("phone_link", "full")
            report = FullSyncReport(
                from_config=boot.from_config,
                from_jsonl=boot.from_jsonl,
                from_localstorage=boot.from_localstorage,
                from_phone_link=boot.from_phone_link,
                from_caught=boot.from_caught,
                total=boot.total,
                phone_link_db_path=pl_path,
                phone_link_contacts_db=pl_count,
                phone_link_message_dbs=msg_dbs,
                watch_folders=len((config.get("phone_link") or {}).get("watch_folders") or []),
            )
        ttl = out.get("auto_delete_caught_seconds")
        if ttl:
            caught_store.prune_older_than(ttl)

        from telelink.notif_seen import reconcile_seen_if_caught_empty

        if reconcile_seen_if_caught_empty(config, caught_store):
            pass  # caught empty but notif-seen had stale dedup entries — cleared

        call_log_store = CallLogStore(out["calls_file"])
        calls_cfg = config.get("calls") or {}
        if calls_cfg.get("enabled", True) is not False and calls_cfg.get(
            "sync_phone_link_db", True
        ):
            from telelink.phone_link_calls import sync_calls_from_phone_link

            sync_calls_from_phone_link(config, call_log_store, contact_store=contact_store)

        call_ttl = calls_cfg.get("ttl_seconds")
        if call_ttl and calls_cfg.get("enabled", True) is not False:
            call_log_store.prune_older_than(call_ttl)

        from telelink.sent_log import prune_sent_log

        prune_sent_log(config)

        from telelink.outtake_share import outtake_auto_delete_seconds, prune_outtake_github

        if outtake_auto_delete_seconds(config):
            try:
                prune_outtake_github(config)
            except Exception:
                pass

        session = cls(
            config=config,
            config_path=path,
            db=db,
            local_storage=ls,
            contact_store=contact_store,
            caught_store=caught_store,
            call_log_store=call_log_store,
            sync_report=report,
        )
        contact_store._on_change = session.on_contacts_changed
        contact_store._cache = session.cache

        from telelink.intake_remind import start_intake_remind_daemon
        from telelink.outtake_prune import start_outtake_prune_daemon
        from telelink.calendar_remind import start_calendar_remind_daemon
        from telelink.calendar_scheduler import start_calendar_scheduler
        from telelink.calls_remind import start_calls_remind_daemon
        from telelink.sync_auto import start_sync_daemon

        ars_mode = os.environ.get("TELELINK_ARS") == "1"

        start_outtake_prune_daemon(session.config_fresh)
        if not ars_mode:
            start_intake_remind_daemon(session.config_fresh)
            start_calendar_scheduler(session.config_fresh)
            start_calendar_remind_daemon(session.config_fresh)
            start_calls_remind_daemon(session.config_fresh)
        start_sync_daemon(session.config_fresh)
        return session


def get_session(*, reload: bool = False) -> TeleLinkSession:
    global _session
    if _session is None or reload:
        _session = TeleLinkSession.bootstrap()
    return _session


def reset_session() -> None:
    global _session
    _session = None
