from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telelink.models import Task
from telelink.task_rows import normalize_task_row


class CaughtStore:
    """Append-only store of caught Phone Link notifications (JSONL)."""

    def __init__(self, caught_file: str, attachments_dir: str) -> None:
        self.caught_file = Path(caught_file)
        self.attachments_dir = Path(attachments_dir)
        self.caught_file.parent.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self._seen_ids: set[str] = set()
        self._write_lock = threading.Lock()
        self._load_seen()

    @property
    def tasks_file(self) -> Path:
        """Legacy alias."""
        return self.caught_file

    def _load_seen(self) -> None:
        if not self.caught_file.exists():
            return
        with self.caught_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("id"):
                        self._seen_ids.add(row["id"])
                except json.JSONDecodeError:
                    continue

    def save(self, task: Task) -> bool:
        with self._write_lock:
            if task.id in self._seen_ids:
                return False
            with self.caught_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")
            self._seen_ids.add(task.id)
            return True

    @staticmethod
    def _parse_timestamp(ts: str) -> datetime | None:
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def prune_older_than(self, max_age_seconds: float) -> int:
        """Drop caught rows older than max_age_seconds. Returns number removed."""
        if max_age_seconds <= 0 or not self.caught_file.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        kept: list[dict[str, Any]] = []
        removed = 0

        with self.caught_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = self._parse_timestamp(row.get("timestamp", ""))
                if ts is None or ts >= cutoff:
                    kept.append(row)
                else:
                    removed += 1

        if removed == 0:
            return 0

        with self.caught_file.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        self._seen_ids = {row["id"] for row in kept if row.get("id")}
        if not kept:
            from telelink.notif_seen import notif_seen_path

            seen = notif_seen_path({"output": {"dir": str(self.caught_file.parent)}})
            if seen.exists() and seen.stat().st_size > 0:
                seen.write_text("", encoding="utf-8")
        return removed

    def list_caught(
        self,
        *,
        limit: int | None = None,
        channel: str | None = None,
        contact: str | None = None,
        sender: str | None = None,
        message_kind: str | None = None,
        contacts_only: bool = False,
        client: str | None = None,
        clients_only: bool = False,
    ) -> list[dict[str, Any]]:
        contact = contact or client
        contacts_only = contacts_only or clients_only

        if not self.caught_file.exists():
            return []

        rows: list[dict[str, Any]] = []
        with self.caught_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = normalize_task_row(json.loads(line))
                if channel and row.get("channel") != channel:
                    continue
                if contact and row.get("contact") != contact:
                    continue
                if message_kind and row.get("message_kind") != message_kind:
                    continue
                if contacts_only and not row.get("contact_matched"):
                    continue
                if sender:
                    s = sender.lower()
                    hay = f"{row.get('sender', '')} {row.get('sender_id', '')}".lower()
                    if s not in hay:
                        continue
                rows.append(row)

        if limit is not None:
            return rows[-limit:]
        return rows

    list_tasks = list_caught

    @staticmethod
    def group_caught(rows: list[dict[str, Any]], by: str) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            row = normalize_task_row(row)
            if by == "channel":
                key = row.get("channel") or "unknown"
            elif by == "platform":
                key = row.get("platform") or row.get("channel") or "unknown"
            elif by in ("contact", "client"):
                key = row.get("contact") or "unknown"
            elif by == "sender":
                key = row.get("sender") or row.get("sender_id") or "unknown"
            elif by == "kind":
                key = row.get("message_kind") or "text"
            else:
                key = "all"
            groups[key].append(row)
        return dict(groups)

    group_tasks = group_caught


TaskStore = CaughtStore
