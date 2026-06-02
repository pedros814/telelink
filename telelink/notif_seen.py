"""Persistent dedup for Windows toast notifications (survives watcher restarts)."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any


def content_fingerprint(title: str, text: str) -> str:
    raw = f"{title.strip()}|{text.strip()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:24]


def notif_seen_path(config: dict[str, Any]) -> Path:
    return Path(config.get("output", {}).get("dir", "./data")) / "notif-seen.txt"


def parse_seen_line(line: str) -> tuple[str, str] | None:
    """Parse ``app_id|note_id|fingerprint`` written by is_new."""
    line = line.strip()
    if not line:
        return None
    parts = line.split("|")
    if len(parts) < 3:
        return None
    slot = f"{parts[0]}|{parts[1]}"
    return slot, parts[2]


def reconcile_seen_if_caught_empty(config: dict[str, Any], caught_store: Any) -> bool:
    """Clear notification dedup when caught log is empty so toasts can be re-ingested."""
    caught = Path(caught_store.caught_file)
    if caught.exists() and caught.stat().st_size > 0:
        return False
    seen = notif_seen_path(config)
    if not seen.exists() or seen.stat().st_size == 0:
        return False
    seen.write_text("", encoding="utf-8")
    return True


class NotificationSeenStore:
    """Track last captured content per (app_id, notification_id) slot."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._fingerprints: dict[str, str] = {}
        self._loaded_mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        self._fingerprints.clear()
        if not self.path.exists():
            self._loaded_mtime = 0.0
            return
        try:
            self._loaded_mtime = self.path.stat().st_mtime
            for line in self.path.read_text(encoding="utf-8").splitlines():
                parsed = parse_seen_line(line)
                if parsed:
                    slot, fp = parsed
                    self._fingerprints[slot] = fp
        except OSError:
            pass

    def _reload_if_stale(self) -> None:
        if not self.path.exists():
            if self._fingerprints:
                self._fingerprints.clear()
                self._loaded_mtime = 0.0
            return
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return
        if mtime != self._loaded_mtime:
            self._load()

    def clear(self) -> None:
        with self._lock:
            self._fingerprints.clear()
            self._loaded_mtime = 0.0
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text("", encoding="utf-8")
            except OSError:
                pass

    def is_new(self, app_id: str, note_id: int, title: str, text: str) -> bool:
        self._reload_if_stale()
        slot = f"{app_id}|{note_id}"
        fp = content_fingerprint(title, text)
        with self._lock:
            if self._fingerprints.get(slot) == fp:
                return False
            self._fingerprints[slot] = fp
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(f"{slot}|{fp}\n")
                self._loaded_mtime = self.path.stat().st_mtime
            except OSError:
                pass
            return True

    def prune_slots(self, active_slots: set[str], *, max_entries: int = 8000) -> None:
        """Drop entries for notifications no longer in the action center."""
        with self._lock:
            if active_slots:
                stale = [k for k in self._fingerprints if k not in active_slots]
                for k in stale:
                    del self._fingerprints[k]
            if len(self._fingerprints) <= max_entries:
                return
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
                keep = lines[-max_entries:]
                self.path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
                self._fingerprints.clear()
                for line in keep:
                    parsed = parse_seen_line(line)
                    if parsed:
                        slot, fp = parsed
                        self._fingerprints[slot] = fp
                self._loaded_mtime = self.path.stat().st_mtime if self.path.exists() else 0.0
            except OSError:
                pass
