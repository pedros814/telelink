"""JSON-backed localStorage — runtime prefs and sync metadata only.

Contacts, caught messages, and config live in their own files (contacts.jsonl,
telelink.db, caught.jsonl, config.yaml). This file must not duplicate those stores.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_STORAGE_VERSION = 2

# Small discovery / runtime pointers (paths, not file contents).
_ALLOWED_PREF_PREFIXES = ("phone_link_",)
_ALLOWED_PREF_KEYS = frozenset(
    {
        "phone_link_contacts_db_path",
        "phone_link_phone_db_path",
    }
)

# Legacy bulk keys removed on load (contacts live in jsonl + sqlite).
_LEGACY_CACHE_KEYS = frozenset(
    {
        "contacts_snapshot",
        "config_overlay",
        "contacts",
        "caught_snapshot",
        "tasks_snapshot",
    }
)

_DEFAULT: dict[str, Any] = {
    "version": _STORAGE_VERSION,
    "prefs": {},
    "last_sync": {},
    "pending": {},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_allowed_pref(key: str) -> bool:
    if key in _ALLOWED_PREF_KEYS:
        return True
    return any(key.startswith(p) for p in _ALLOWED_PREF_PREFIXES)


class LocalStorage:
    """Runtime prefs, sync timestamps, and in-flight pending rows — not canonical data."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._dirty = False
        self._save_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = dict(_DEFAULT)
            self._dirty = True
            self._save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            self._data = {}
        self._normalize_structure()
        if self._prune_legacy():
            self._dirty = True
        if self._dirty:
            self._save()

    def _normalize_structure(self) -> None:
        self._data.setdefault("version", _STORAGE_VERSION)
        self._data.setdefault("prefs", {})
        self._data.setdefault("last_sync", {})
        self._data.setdefault("pending", {})
        if not isinstance(self._data.get("prefs"), dict):
            self._data["prefs"] = {}
        if not isinstance(self._data.get("last_sync"), dict):
            self._data["last_sync"] = {}
        if not isinstance(self._data.get("pending"), dict):
            self._data["pending"] = {}
        self._data["version"] = _STORAGE_VERSION

    def _prune_legacy(self) -> bool:
        """Drop duplicated / deprecated cache blobs. Returns True if anything removed."""
        changed = False

        cache = self._data.pop("cache", None)
        if cache:
            changed = True
            if isinstance(cache, dict):
                for key in cache:
                    if key not in _LEGACY_CACHE_KEYS:
                        log.debug("dropped legacy localStorage cache key: %s", key)

        prefs = self._data.get("prefs") or {}
        if isinstance(prefs, dict):
            stripped = {k: v for k, v in prefs.items() if _is_allowed_pref(k)}
            if len(stripped) != len(prefs):
                self._data["prefs"] = stripped
                changed = True

        pending = self._data.get("pending") or {}
        if isinstance(pending, dict):
            contacts = pending.get("contacts")
            if contacts is not None and not contacts:
                pending.pop("contacts", None)
                changed = True
            if not pending:
                self._data["pending"] = {}

        return changed

    def _save(self) -> None:
        payload = json.dumps(self._data, indent=2, ensure_ascii=False)
        with self._save_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            last_err: OSError | None = None
            for attempt in range(6):
                tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                try:
                    tmp.write_text(payload, encoding="utf-8")
                    tmp.replace(self.path)
                    self._dirty = False
                    return
                except OSError as exc:
                    last_err = exc
                    with contextlib.suppress(OSError):
                        tmp.unlink(missing_ok=True)
                    time.sleep(0.08 * (attempt + 1))
            # OneDrive / AV sometimes blocks atomic replace — direct write last resort.
            try:
                self.path.write_text(payload, encoding="utf-8")
                self._dirty = False
                if last_err:
                    log.debug(
                        "localStorage atomic save failed (%s); wrote directly to %s",
                        last_err,
                        self.path,
                    )
                return
            except OSError as exc:
                last_err = exc
            log.warning("localStorage save failed for %s: %s", self.path, last_err)
            if last_err:
                raise last_err

    def reload(self) -> None:
        self._load()

    def reset(self) -> None:
        """Wipe to empty runtime state (prefs, sync times, pending)."""
        self._data = dict(_DEFAULT)
        self._dirty = True
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in ("prefs", "last_sync", "pending", "version"):
            self._data[key] = value
            self._dirty = True
            self._save()
            return
        log.debug("localStorage: ignoring top-level key %r (use pref/mark_synced)", key)

    def pref(self, key: str, default: Any = None) -> Any:
        return self._data.get("prefs", {}).get(key, default)

    def set_pref(self, key: str, value: Any) -> None:
        if not _is_allowed_pref(key):
            log.debug("localStorage: refusing pref %r (not a runtime pointer)", key)
            return
        prefs = self._data.setdefault("prefs", {})
        if prefs.get(key) == value:
            return
        prefs[key] = value
        self._dirty = True
        self._save()

    def cache_get(self, key: str, default: Any = None) -> Any:
        """Deprecated — bulk cache removed. Contacts live in jsonl/sqlite."""
        if key in _LEGACY_CACHE_KEYS:
            return default
        log.debug("localStorage.cache_get(%r) ignored — use canonical stores", key)
        return default

    def cache_set(self, key: str, value: Any) -> None:
        """Deprecated — no-op for legacy keys; refuses to store bulk payloads."""
        if key in _LEGACY_CACHE_KEYS:
            return
        if isinstance(value, (list, dict)) and value:
            log.debug("localStorage.cache_set(%r) refused — not a runtime pointer", key)
        return

    def mark_synced(self, source: str) -> None:
        last = self._data.setdefault("last_sync", {})
        stamp = _now_iso()
        if last.get(source) == stamp:
            return
        last[source] = stamp
        self._dirty = True
        self._save()

    def mark_synced_many(self, *sources: str) -> None:
        """Update several sync timestamps in one disk write."""
        if not sources:
            return
        last = self._data.setdefault("last_sync", {})
        stamp = _now_iso()
        changed = False
        for source in sources:
            if last.get(source) != stamp:
                last[source] = stamp
                changed = True
        if not changed:
            return
        self._dirty = True
        self._save()

    def last_sync(self, source: str) -> str | None:
        return self._data.get("last_sync", {}).get(source)

    def pending_contacts(self) -> list[dict[str, Any]]:
        raw = self._data.get("pending", {}).get("contacts") or []
        return list(raw) if isinstance(raw, list) else []

    def set_pending_contacts(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self.clear_pending_contacts()
            return
        self._data.setdefault("pending", {})["contacts"] = rows
        self._dirty = True
        self._save()

    def clear_pending_contacts(self) -> None:
        pending = self._data.setdefault("pending", {})
        if "contacts" not in pending:
            return
        pending.pop("contacts", None)
        if not pending:
            self._data["pending"] = {}
        self._dirty = True
        self._save()
