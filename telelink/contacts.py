"""Contacts store — names, numbers, match rules for notifications, send/SMS."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telelink.classify import normalize_sender_id

_PHONEISH = re.compile(r"^[\d\s\-\+\(\)\.]{7,}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_phone(value: str) -> str:
    """Normalize to sms:-friendly form (digits, optional leading +)."""
    raw = (value or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return digits


def dial_digits(value: str) -> str:
    """Digits-only E.164 for sms:/smsto: URIs (Phone Link ignores + in the host)."""
    norm = normalize_phone(value)
    if not norm:
        return ""
    return re.sub(r"\D", "", norm)


def dial_phone(row: dict[str, Any]) -> str:
    """Pick the real number from a contact row."""
    for field in ("phone", "notes"):
        val = str(row.get(field) or "").strip()
        if looks_like_phone(val):
            return normalize_phone(val)
    return ""


def _coerce_contact_fields(name: str, phone: str) -> tuple[str, str]:
    """Fix common swaps: name in phone field, etc."""
    name = (name or "").strip()
    phone_raw = (phone or "").strip()

    if phone_raw and not looks_like_phone(phone_raw):
        nickname = phone_raw
        if looks_like_phone(name):
            return nickname, normalize_phone(name)
        if name.lower() in ("contact", "name", ""):
            raise ValueError(
                f"'{nickname}' is not a phone number — use: contacts add {nickname} +15551234567"
            )

    if name and looks_like_phone(name) and not looks_like_phone(phone_raw):
        phone_raw, name = name, phone_raw or "Contact"

    phone_norm = normalize_phone(phone_raw) if phone_raw else ""
    if phone_raw and not phone_norm:
        raise ValueError(f"'{phone_raw}' is not a valid phone number")

    return name, phone_norm


def ascii_match_token(name: str) -> str:
    """Letters/digits/spaces only — e.g. Mom🩵 → mom for lookup aliases."""
    return "".join(
        ch.lower() if ch.isalpha() else ch
        for ch in (name or "")
        if ch.isascii() and (ch.isalnum() or ch.isspace())
    ).strip()


def _repair_contact_row(row: dict[str, Any]) -> dict[str, Any]:
    """Repair swapped fields from older saves."""
    name = str(row.get("name") or "").strip()
    phone = str(row.get("phone") or "").strip()
    client = str(row.get("client") or "").strip()

    if phone and not looks_like_phone(phone):
        nickname = phone
        if looks_like_phone(client):
            row = dict(row)
            row["name"] = nickname if name.lower() in ("contact", "name", "") else name
            row["phone"] = normalize_phone(client)
            row["client"] = "" if name.lower() in ("contact", "name", "") else client
            return row
        if looks_like_phone(name):
            row = dict(row)
            row["name"] = nickname
            row["phone"] = normalize_phone(name)
            row["client"] = client
            return row

    if name and looks_like_phone(name) and not looks_like_phone(phone):
        row = dict(row)
        row["phone"] = normalize_phone(name)
        row["name"] = phone or "Contact"
        return row

    if phone and looks_like_phone(phone):
        row = dict(row)
        row["phone"] = normalize_phone(phone)

    row = dict(row)
    if "match" not in row:
        row["match"] = []
    legacy_client = str(row.pop("client", "") or "").strip()
    if legacy_client and legacy_client.lower() not in (row.get("name") or "").lower():
        m = list(row["match"])
        if legacy_client not in m:
            m.append(legacy_client)
        row["match"] = m
    if "managed" not in row:
        row["managed"] = row.get("name", "").lower() != "myself"
    if "platform" not in row:
        row["platform"] = ""
    name = str(row.get("name") or "").strip()
    ascii_name = ascii_match_token(name)
    if ascii_name and ascii_name != name.lower():
        m = list(row.get("match") or [])
        if ascii_name not in m:
            m.append(ascii_name)
            row["match"] = m
        for part in re.split(r"\s+", ascii_name):
            if len(part) >= 2 and part not in m:
                m.append(part)
                row["match"] = m
    return row


def clean_send_target(value: str) -> str:
    """Fix glued phone prefix + name (e.g. 57myself → myself from phantom keypresses)."""
    raw = (value or "").strip()
    if not raw or looks_like_phone(raw):
        return raw
    m = re.match(r"^(\d{1,6})([a-zA-Z].+)$", raw)
    if m:
        return m.group(2).strip()
    return raw


def resolve_targets(value: str) -> list[str]:
    """Candidate lookup keys for send / resolve (handles 57myself-style glitches)."""
    raw = (value or "").strip()
    if not raw:
        return []
    out = [raw]
    cleaned = clean_send_target(raw)
    if cleaned != raw:
        out.append(cleaned)
    return out


def looks_like_phone(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    if not _PHONEISH.match(s):
        return False
    return len(re.sub(r"\D", "", s)) >= 7


class ContactStore:
    def __init__(
        self,
        contacts_file: str,
        *,
        db: Any | None = None,
        local_storage: Any | None = None,
        on_change: Any | None = None,
    ) -> None:
        self.contacts_file = Path(contacts_file)
        self.contacts_file.parent.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.local_storage = local_storage
        self._on_change = on_change
        self._by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def reload_from_disk(self) -> None:
        self._load()
        cache = getattr(self, "_cache", None)
        if cache is not None:
            cache.invalidate("contacts")
            cache.invalidate("resolve")

    def export_jsonl(self) -> None:
        self._persist_jsonl_only()

    def _load(self) -> None:
        self._by_id.clear()
        if self.db:
            for row in self.db.all_contacts():
                row = _repair_contact_row(row)
                cid = row.get("id")
                if cid:
                    self._by_id[cid] = row
        if not self.contacts_file.exists():
            return
        repaired_any = False
        with self.contacts_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    row = _repair_contact_row(raw)
                    if row != raw:
                        repaired_any = True
                except json.JSONDecodeError:
                    continue
                cid = row.get("id")
                if cid:
                    self._by_id[cid] = row
        if repaired_any:
            self._persist()

    def _persist_jsonl_only(self) -> None:
        rows = sorted(self._by_id.values(), key=lambda r: (r.get("name") or "").lower())
        with self.contacts_file.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _persist(self) -> None:
        rows = sorted(self._by_id.values(), key=lambda r: (r.get("name") or "").lower())
        if self.db:
            for row in rows:
                self.db.upsert_contact(row)
        self._persist_jsonl_only()
        if self._on_change:
            self._on_change()

    def list_contacts(self, *, query: str | None = None) -> list[dict[str, Any]]:
        if not query:
            cache = getattr(self, "_cache", None)
            if cache is not None:
                return cache.get_or_set(
                    "contacts:all",
                    lambda: sorted(
                        [_repair_contact_row(r) for r in self._by_id.values()],
                        key=lambda r: (r.get("name") or "").lower(),
                    ),
                )
        rows = [_repair_contact_row(r) for r in self._by_id.values()]
        if query:
            q = query.lower()
            rows = [
                r
                for r in rows
                if q in (r.get("name") or "").lower()
                or q in (r.get("phone") or "").lower()
                or any(q in str(a).lower() for a in (r.get("aliases") or []))
                or q in " ".join(str(x) for x in (r.get("match") or [])).lower()
            ]
        return sorted(rows, key=lambda r: (r.get("name") or "").lower())

    def get(self, contact_id: str) -> dict[str, Any] | None:
        return self._by_id.get(contact_id)

    def upsert(
        self,
        *,
        name: str,
        phone: str = "",
        email: str = "",
        notes: str = "",
        aliases: list[str] | None = None,
        match: list[str] | None = None,
        platform: str = "",
        managed: bool | None = None,
        contact_id: str | None = None,
    ) -> dict[str, Any]:
        name, phone = _coerce_contact_fields(name, phone)
        if not name:
            raise ValueError("contact name is required")
        if not phone:
            raise ValueError("phone number is required")
        now = _now_iso()
        existing = None
        if contact_id:
            existing = self._by_id.get(contact_id)
        if not existing:
            for row in self._by_id.values():
                if row.get("name", "").lower() == name.lower():
                    existing = row
                    break
        if existing:
            row = existing
            row["name"] = name
            if phone:
                row["phone"] = phone
            if email:
                row["email"] = email.strip()
            if notes:
                row["notes"] = notes.strip()
            if aliases is not None:
                row["aliases"] = [a.strip() for a in aliases if a.strip()]
            if match is not None:
                row["match"] = [a.strip() for a in match if a.strip()]
            if platform:
                row["platform"] = platform.strip()
            if managed is not None:
                row["managed"] = managed
            row["updated_at"] = now
        else:
            default_match = [name.lower()]
            if phone:
                default_match.append(phone)
                default_match.append(re.sub(r"\D", "", phone))
            row = {
                "id": contact_id or str(uuid.uuid4()),
                "name": name,
                "phone": phone,
                "email": email.strip(),
                "notes": notes.strip(),
                "aliases": [a.strip() for a in (aliases or []) if a.strip()],
                "match": [a.strip() for a in (match or default_match) if a.strip()],
                "platform": platform.strip(),
                "managed": managed if managed is not None else True,
                "created_at": now,
                "updated_at": now,
            }
            self._by_id[row["id"]] = row
        self._persist()
        return row

    def remove(self, name_or_id: str) -> bool:
        key = name_or_id.strip().lower()
        for cid, row in list(self._by_id.items()):
            if cid == name_or_id or (row.get("name") or "").lower() == key:
                del self._by_id[cid]
                if self.db:
                    self.db.delete_contact(cid)
                self._persist()
                return True
        return False

    def resolve(self, target: str) -> dict[str, Any]:
        """Resolve contact name, alias, or phone string to {name, phone, contact?}."""
        candidates = resolve_targets(target)
        if not candidates:
            raise ValueError("missing contact name or phone number")

        last_error: ValueError | None = None
        for raw in candidates:
            try:
                return self._resolve_one(raw)
            except ValueError as exc:
                last_error = exc
        raise last_error or ValueError(f"no contact or number found for '{target}'")

    @staticmethod
    def _query_keys(raw: str) -> set[str]:
        keys: set[str] = set()
        text = (raw or "").strip()
        if not text:
            return keys
        keys.add(text.lower())
        cleaned = text.lower().strip().rstrip("?!.")
        if cleaned:
            keys.add(cleaned)
        ascii_t = ascii_match_token(text)
        if ascii_t:
            keys.add(ascii_t)
        return keys

    @staticmethod
    def _row_lookup_keys(row: dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        name = str(row.get("name") or "").strip()
        if name:
            keys.add(name.lower())
            ascii_n = ascii_match_token(name)
            if ascii_n:
                keys.add(ascii_n)
        phone_field = str(row.get("phone") or "")
        if phone_field:
            keys.add(phone_field.lower())
            keys.add(re.sub(r"\D", "", phone_field))
        for field in ("aliases", "match"):
            for item in row.get(field) or []:
                s = str(item).strip()
                if not s:
                    continue
                keys.add(s.lower())
                ascii_m = ascii_match_token(s)
                if ascii_m:
                    keys.add(ascii_m)
        return keys

    def _resolve_one(self, raw: str) -> dict[str, Any]:
        if looks_like_phone(raw):
            return {"name": raw, "phone": normalize_phone(raw), "contact": None}

        query_keys = self._query_keys(raw)
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []

        for row in self._by_id.values():
            row = _repair_contact_row(row)
            name = (row.get("name") or "").lower()
            phone_field = str(row.get("phone") or "")
            dial = dial_phone(row)
            row_keys = self._row_lookup_keys(row)

            if query_keys & row_keys:
                exact.append(row)
                continue
            if dial and normalize_sender_id(raw) == normalize_sender_id(dial):
                exact.append(row)
                continue
            if any(key and key in name for key in query_keys):
                partial.append(row)
            elif not looks_like_phone(phone_field) and any(
                key in phone_field.lower() for key in query_keys if key
            ):
                partial.append(row)

        if len(exact) == 1:
            row = exact[0]
            number = dial_phone(row)
            if not number:
                raise ValueError(f"contact '{row.get('name')}' has no phone number")
            display = row.get("name") or raw
            return {"name": display, "phone": number, "contact": row}

        if len(exact) > 1:
            names = ", ".join(r.get("name", "?") for r in exact)
            raise ValueError(f"ambiguous contact '{raw}' — matches: {names}")

        if len(partial) == 1:
            row = partial[0]
            number = dial_phone(row)
            if not number:
                raise ValueError(f"contact '{row.get('name')}' has no phone number")
            display = row.get("name") or raw
            if not looks_like_phone(str(row.get("phone") or "")):
                display = str(row.get("phone") or display)
            return {"name": display, "phone": number, "contact": row}

        if len(partial) > 1:
            names = ", ".join(r.get("name", "?") for r in partial[:5])
            raise ValueError(f"ambiguous contact '{raw}' — did you mean: {names}?")

        raise ValueError(f"no contact or number found for '{raw}' — try contacts add")

    def import_config_contacts(self, entries: list[dict[str, Any]]) -> int:
        """Import legacy config `clients` / `contacts` list into contacts.jsonl."""
        added = 0
        for entry in entries:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            raw_patterns = [str(p).strip() for p in (entry.get("match") or []) if str(p).strip()]
            phone = ""
            text_patterns: list[str] = []
            for pat in raw_patterns:
                if looks_like_phone(pat):
                    if not phone:
                        phone = normalize_phone(pat)
                else:
                    text_patterns.append(pat)
            if not phone:
                continue
            match = list(dict.fromkeys(
                text_patterns + [name.lower(), phone, re.sub(r"\D", "", phone)]
            ))
            exists = any((r.get("name") or "").lower() == name.lower() for r in self._by_id.values())
            if not exists:
                added += 1
            self.upsert(
                name=name,
                phone=phone,
                match=match,
                managed=bool(entry.get("managed", True)),
                platform=str(entry.get("platform") or ""),
            )
        return added

    def sync_from_config(self, config: dict[str, Any]) -> int:
        entries = config.get("contacts") or config.get("clients") or []
        return self.import_config_contacts(entries)

    def sync_from_caught(self, rows: list[dict[str, Any]], *, limit: int = 50) -> int:
        """Suggest contacts from caught-notification senders with phone-like IDs."""
        seen: set[str] = set()
        added = 0
        for row in reversed(rows):
            sender = str(row.get("sender") or "").strip()
            sid = str(row.get("sender_id") or "").strip()
            phone_raw = sender if looks_like_phone(sender) else sid if looks_like_phone(sid) else ""
            if not phone_raw:
                continue
            phone = normalize_phone(phone_raw)
            if phone in seen:
                continue
            seen.add(phone)
            name = sender if not looks_like_phone(sender) else phone
            if any(normalize_phone(r.get("phone", "")) == phone for r in self._by_id.values()):
                continue
            self.upsert(
                name=name[:60],
                phone=phone,
                match=[name.lower(), phone],
                managed=False,
                notes="imported from caught",
            )
            added += 1
            if added >= limit:
                break
        return added

    sync_from_tasks = sync_from_caught
