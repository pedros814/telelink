"""Phone Link call notifications — detect, store, prune, and display."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from telelink.classify import normalize_sender_id, resolve_contact
from telelink.models import utc_now_iso

if TYPE_CHECKING:
    from telelink.contacts import ContactStore

# Notification body/title hints (Phone Link / Windows call toasts).
_CALL_HINTS = (
    "missed call",
    "incoming call",
    "outgoing call",
    "call ended",
    "call declined",
    "call failed",
    "voicemail",
    "facetime",
    "video call",
    "audio call",
    "declined call",
    "cancelled call",
    "canceled call",
)

_MISSED_HINTS = ("missed call", "missed facetime", "missed video", "no answer")
_INCOMING_HINTS = ("incoming call", "incoming facetime", "incoming video")
_OUTGOING_HINTS = ("outgoing call", "outgoing facetime", "outgoing video", "call ended")

_SCENARIO_RE = re.compile(
    r'scenario\s*=\s*["\']?(incomingCall|missedCall|reminder|alarm)["\']?',
    re.IGNORECASE,
)

# "Missed call from Mom" / "Incoming call - mobile"
_FROM_RE = re.compile(
    r"^(?:missed|incoming|outgoing|declined|cancelled|canceled)\s+call\s+from\s+(.+)$",
    re.IGNORECASE,
)


@dataclass
class CallEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "unknown"  # missed | incoming | outgoing | unknown
    caller: str = ""
    sender_id: str = ""
    contact: str = ""
    contact_matched: bool = False
    body: str = ""
    notification_app: str = ""
    source: str = "phone_link"
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scenario_from_xml(xml: str) -> str | None:
    if not xml:
        return None
    m = _SCENARIO_RE.search(xml)
    if not m:
        return None
    raw = m.group(1).lower()
    if raw == "incomingcall":
        return "incoming"
    if raw == "missedcall":
        return "missed"
    return raw


def classify_call_kind(title: str, body: str, *, xml: str = "") -> str | None:
    """Return call kind if this looks like a call notification, else None."""
    scenario = scenario_from_xml(xml)
    if scenario in ("incoming", "missed"):
        return scenario

    combined = f"{title}\n{body}".lower()
    if not any(h in combined for h in _CALL_HINTS):
        return None

    if any(h in combined for h in _MISSED_HINTS):
        return "missed"
    if any(h in combined for h in _INCOMING_HINTS):
        return "incoming"
    if any(h in combined for h in _OUTGOING_HINTS):
        return "outgoing"
    if "missed" in combined:
        return "missed"
    if "incoming" in combined:
        return "incoming"
    if "outgoing" in combined or "call ended" in combined:
        return "outgoing"
    return "unknown"


def parse_caller(title: str, body: str) -> str:
    title = (title or "").strip()
    body = (body or "").strip()
    for text in (body, title):
        m = _FROM_RE.match(text)
        if m:
            return m.group(1).strip()
    if title and title.lower() not in _CALL_HINTS and not any(h in title.lower() for h in _CALL_HINTS):
        return title
    if body and body.lower() not in {h for h in _CALL_HINTS}:
        low = body.lower()
        for hint in _CALL_HINTS:
            if low == hint:
                break
        else:
            return body
    return title or body or "unknown"


class CallLogStore:
    """Append-only call log (JSONL) with TTL prune."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._write_lock = threading.Lock()
        self._load_seen()

    def _load_seen(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("id"):
                        self._seen.add(row["id"])
                except json.JSONDecodeError:
                    continue

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

    def save(self, entry: CallEntry) -> bool:
        with self._write_lock:
            if entry.id in self._seen:
                return False
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            self._seen.add(entry.id)
            return True

    def upsert_entries(self, entries: list[CallEntry]) -> int:
        """Insert entries; skip ids already in the log. Returns count added."""
        added = 0
        with self._write_lock:
            to_write: list[CallEntry] = []
            for entry in entries:
                if entry.id in self._seen:
                    continue
                to_write.append(entry)
                self._seen.add(entry.id)
            if not to_write:
                return 0
            with self.path.open("a", encoding="utf-8") as f:
                for entry in to_write:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            added = len(to_write)
        return added

    def list_calls(
        self,
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.path.exists():
            return rows
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if kind and str(row.get("kind", "")).lower() != kind.lower():
                    continue
                rows.append(row)
        rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        if limit is not None:
            return rows[:limit]
        return rows

    def count_missed(self) -> int:
        return len(self.list_calls(kind="missed"))

    def prune_older_than(self, max_age_seconds: float) -> int:
        if max_age_seconds <= 0 or not self.path.exists():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        with self._write_lock:
            kept: list[dict[str, Any]] = []
            removed = 0
            with self.path.open(encoding="utf-8") as f:
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
            with self.path.open("w", encoding="utf-8") as f:
                for row in kept:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._seen = {row["id"] for row in kept if row.get("id")}
            return removed


def call_log_path(config: dict[str, Any]) -> Path:
    calls = config.get("calls") or {}
    out = config.get("output") or {}
    out_dir = Path(out.get("dir", "./data"))
    name = calls.get("file") or "calls.jsonl"
    return out_dir / name


def call_log_enabled(config: dict[str, Any]) -> bool:
    calls = config.get("calls") or {}
    return calls.get("enabled", True) is not False


def call_log_ttl_seconds(config: dict[str, Any]) -> int:
    calls = config.get("calls") or {}
    return int(calls.get("ttl_seconds") or 86400)


def try_record_call(
    *,
    config: dict[str, Any],
    store: CallLogStore,
    title: str,
    body: str,
    notification_app: str = "",
    xml: str = "",
    contact_store: "ContactStore | None" = None,
) -> CallEntry | None:
    """If notification is a call, append to call log and return the entry."""
    if not call_log_enabled(config):
        return None

    kind = classify_call_kind(title, body, xml=xml)
    if kind is None:
        return None

    caller = parse_caller(title, body)
    contact, matched = resolve_contact(config, caller, body, store=contact_store)
    entry = CallEntry(
        kind=kind,
        caller=caller,
        sender_id=normalize_sender_id(caller),
        contact=contact,
        contact_matched=matched,
        body=body or title,
        notification_app=notification_app,
    )
    if store.save(entry):
        return entry
    return None
