"""Phone Link contacts.db — discover, read-only snapshot, contact matching."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telelink.contacts import looks_like_phone, normalize_phone
from telelink.harvest import _pkg_roots

log = logging.getLogger(__name__)

_SKIP_NAMES = frozenset({"my number", "my phone", "unknown"})

# Phone Link mirrors iPhone contacts per paired device:
# .../LocalCache/Indexed/<device-guid>/System/Database/contacts.db
# Do not use wide ** globs here — the package cache is huge and slow to scan.
_CONTACTS_DB_GLOB = "LocalCache/Indexed/*/System/Database/contacts.db"

_CACHE_PREF = "phone_link_contacts_db_path"

_APP_SENDERS = frozenset(
    {
        "messenger",
        "instagram",
        "facebook",
        "whatsapp",
        "telegram",
        "signal",
        "snapchat",
        "phone link",
        "your phone",
        "messages",
        "mail",
        "zoho mail",
        "gmail",
        "cash app",
        "offerup",
        "scoopz",
    }
)

_BODY_NAME_RE = re.compile(
    r"^([A-Za-z][\w'.\-]{0,40})\s+(.{2,})$",
)


@dataclass(frozen=True)
class ContactsDbCandidate:
    path: Path
    contact_rows: int = 0
    phone_rows: int = 0
    mtime: float = 0.0
    valid: bool = False

    @property
    def score(self) -> float:
        """Prefer populated, recently synced databases."""
        if not self.valid:
            return -1.0
        return self.contact_rows * 1_000_000 + self.phone_rows * 1_000 + self.mtime


def _expand_config_path(raw: str) -> Path:
    from telelink.config import expand_path

    return expand_path(raw)


def _local_storage(config: dict[str, Any] | None) -> Any | None:
    """Read prefs from localstorage.json only — never bootstraps TeleLink session."""
    path: str | None = None
    if config:
        path = (config.get("output") or {}).get("localstorage_file")
    if not path:
        default = Path.cwd() / "data" / "localstorage.json"
        if default.exists():
            path = str(default)
    if not path:
        return None
    try:
        from telelink.local_storage import LocalStorage

        return LocalStorage(path)
    except Exception:
        return None


def _snapshot_contacts_db(src: Path) -> Path | None:
    """Fallback copy when immutable open fails. Never writes to Phone Link paths."""
    try:
        if not src.is_file() or src.stat().st_size < 512:
            return None
        key = hashlib.sha256(str(src.resolve()).encode()).hexdigest()[:16]
        dest_dir = Path(tempfile.gettempdir()) / "telelink" / "snapshots"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"contacts_{key}.db"
        shutil.copyfile(src, dest)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.is_file():
                try:
                    shutil.copyfile(side, Path(str(dest) + suffix))
                except OSError:
                    pass
        return dest
    except OSError as exc:
        log.debug("contacts.db snapshot failed for %s: %s", src, exc)
        return None


def _connect_contacts_db_readonly(db_path: Path) -> sqlite3.Connection | None:
    """
    Open Phone Link contacts.db without blocking on locks.
    Tries immutable URI first (safe while Phone Link is running), then a temp copy.
    """
    resolved = db_path.resolve()
    uris = (
        f"file:{resolved}?mode=ro&immutable=1",
        f"file:{resolved}?mode=ro",
    )
    for uri in uris:
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=1.5)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return conn
        except sqlite3.Error:
            continue
    work = _snapshot_contacts_db(resolved)
    if not work:
        return None
    try:
        return sqlite3.connect(f"file:{work}?mode=ro", uri=True, timeout=1.5)
    except sqlite3.Error:
        return None


def _probe_contacts_db(db_path: Path) -> tuple[int, int]:
    """Return (contact_rows, phone_rows) or (-1, -1) if not a Phone Link contacts DB."""
    conn = _connect_contacts_db_readonly(db_path)
    if not conn:
        return -1, -1
    try:
        tables = {
            r[0].lower()
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "contact" not in tables:
            return -1, -1
        contacts = int(conn.execute("SELECT COUNT(*) FROM contact").fetchone()[0])
        phones = 0
        if "phonenumber" in tables:
            phones = int(conn.execute("SELECT COUNT(*) FROM phonenumber").fetchone()[0])
        if contacts <= 0:
            return -1, -1
        return contacts, phones
    except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
        log.debug("contacts.db probe failed for %s: %s", db_path, exc)
        return -1, -1
    finally:
        conn.close()


_discovery_method: str = "none"


def get_contacts_discovery_method() -> str:
    """``primary`` | ``fallback`` | ``none`` — set by last ``discover_contacts_databases``."""
    return _discovery_method


def _discover_contacts_primary() -> dict[Path, ContactsDbCandidate]:
    """Glob Phone Link package paths only (unchanged primary discovery)."""
    found: dict[Path, ContactsDbCandidate] = {}
    for root in _pkg_roots():
        try:
            for path in root.glob(_CONTACTS_DB_GLOB):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in found:
                    continue
                try:
                    mtime = resolved.stat().st_mtime
                except OSError:
                    continue
                found[resolved] = ContactsDbCandidate(path=resolved, mtime=mtime)
        except OSError:
            continue
    return found


def _candidates_from_found(
    found: dict[Path, ContactsDbCandidate],
    *,
    probe: bool,
) -> list[ContactsDbCandidate]:
    out: list[ContactsDbCandidate] = []
    for cand in found.values():
        if probe:
            contacts, phones = _probe_contacts_db(cand.path)
            out.append(
                ContactsDbCandidate(
                    path=cand.path,
                    contact_rows=max(contacts, 0),
                    phone_rows=max(phones, 0),
                    mtime=cand.mtime,
                    valid=contacts > 0,
                )
            )
        else:
            out.append(cand)
    return out


def _load_config_for_discovery(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is not None:
        return config
    try:
        from telelink.config import load_config

        return load_config()
    except Exception:
        return {}


def discover_contacts_databases(
    *,
    probe: bool = True,
    config: dict[str, Any] | None = None,
) -> list[ContactsDbCandidate]:
    """
    Find Phone Link contacts.db files under YourPhone / Cross Device packages only.
    Does not scan the whole disk — only known package layouts.
    Falls back to scoped filesystem search when primary finds no files or no valid DB after probe.
    """
    global _discovery_method

    found = _discover_contacts_primary()
    out = _candidates_from_found(found, probe=probe)
    used_fallback = False

    need_fallback = not found or (probe and not any(c.valid for c in out))
    if need_fallback:
        from telelink.phone_link_fallback import fallback_find_contacts_databases

        extra_paths = fallback_find_contacts_databases(_load_config_for_discovery(config))
        if extra_paths:
            used_fallback = True
            for path in extra_paths:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in found:
                    continue
                try:
                    mtime = resolved.stat().st_mtime
                except OSError:
                    continue
                found[resolved] = ContactsDbCandidate(path=resolved, mtime=mtime)
            out = _candidates_from_found(found, probe=probe)

    if probe:
        has_result = any(c.valid for c in out)
    else:
        has_result = bool(out)

    if has_result:
        _discovery_method = "fallback" if used_fallback else "primary"
    else:
        _discovery_method = "none"

    return sorted(out, key=lambda c: c.score, reverse=True)


def _pick_best_candidate(candidates: list[ContactsDbCandidate]) -> ContactsDbCandidate | None:
    valid = [c for c in candidates if c.valid]
    return valid[0] if valid else None


def _cached_path_still_ok(
    cached: Path,
    candidates: list[ContactsDbCandidate],
) -> bool:
    """Keep cached path if still valid and competitive (avoids flipping between device GUIDs)."""
    if not cached.is_file():
        return False
    match = next((c for c in candidates if c.path == cached.resolve()), None)
    if not match or not match.valid:
        return False
    best = _pick_best_candidate(candidates)
    if not best or best.path == cached.resolve():
        return True
    # Switch only if another DB is clearly newer and has more contacts.
    if (
        best.contact_rows >= match.contact_rows + 3
        and best.mtime > match.mtime + 3600
    ):
        return False
    return True


def clear_phone_link_contact_cache() -> None:
    """Drop in-memory Phone Link contacts.db index (force re-read on next lookup)."""
    _index.clear()


def resolve_contacts_db_path(
    config: dict[str, Any] | None = None,
    *,
    local_storage: Any | None = None,
    candidates: list[ContactsDbCandidate] | None = None,
    force: bool = False,
) -> Path | None:
    """
    Resolve contacts.db: config override → validated cache → best auto-discovery.
    Never raises; returns None when Phone Link has not synced contacts yet.
    """
    ls = local_storage if local_storage is not None else _local_storage(config)

    if config:
        pl = config.get("phone_link") or {}
        raw = str(pl.get("contacts_db") or "").strip()
        if raw:
            explicit = _expand_config_path(raw)
            if explicit.is_file():
                contacts, _phones = _probe_contacts_db(explicit)
                if contacts > 0:
                    if ls:
                        ls.set_pref(_CACHE_PREF, str(explicit.resolve()))
                    return explicit.resolve()
                log.warning(
                    "phone_link.contacts_db is set but not a valid Phone Link contacts DB: %s",
                    explicit,
                )
            else:
                log.warning("phone_link.contacts_db not found: %s", explicit)

    if candidates is None:
        candidates = discover_contacts_databases(probe=True, config=config)
    if ls and not force:
        cached_raw = ls.pref(_CACHE_PREF)
        if cached_raw:
            try:
                cached = Path(cached_raw).resolve()
                if _cached_path_still_ok(cached, candidates):
                    return cached
            except OSError:
                pass

    best = _pick_best_candidate(candidates)
    if not best:
        return None

    if ls:
        ls.set_pref(_CACHE_PREF, str(best.path))
    return best.path


def describe_contacts_db_discovery(
    config: dict[str, Any] | None = None,
    *,
    local_storage: Any | None = None,
) -> dict[str, Any]:
    """Summary for config/doctor — all candidates + chosen path."""
    from telelink.phone_link_fallback import fallback_status

    candidates = discover_contacts_databases(probe=True, config=config)
    chosen = resolve_contacts_db_path(
        config, local_storage=local_storage, candidates=candidates
    )
    chosen_resolved = chosen.resolve() if chosen else None
    return {
        "chosen": str(chosen) if chosen else None,
        "discovery_method": get_contacts_discovery_method(),
        "fallback": fallback_status(config),
        "candidates": [
            {
                "path": str(c.path),
                "contacts": c.contact_rows,
                "phones": c.phone_rows,
                "valid": c.valid,
                "chosen": chosen_resolved is not None and c.path == chosen_resolved,
            }
            for c in candidates
        ],
    }


@dataclass
class PhoneLinkContact:
    contact_id: int
    name: str
    phones: list[str] = field(default_factory=list)
    match_keys: list[str] = field(default_factory=list)


def _display_name(row: dict[str, Any]) -> str:
    display = str(row.get("display_name") or "").strip()
    if display:
        return display
    given = str(row.get("given_name") or "").strip()
    family = str(row.get("family_name") or "").strip()
    nick = str(row.get("nickname") or "").strip()
    if given and family:
        return f"{given} {family}".strip()
    if given:
        return given
    if family:
        return family
    if nick:
        return nick
    return ""


def _build_match_keys(name: str, phones: list[str]) -> list[str]:
    from telelink.contacts import ascii_match_token

    keys: list[str] = []
    if name:
        low = name.lower()
        keys.append(low)
        ascii_name = ascii_match_token(name)
        if ascii_name and ascii_name != low:
            keys.append(ascii_name)
        for part in re.split(r"\s+", ascii_name or low):
            if len(part) >= 2:
                keys.append(part)
    for phone in phones:
        keys.append(phone)
        digits = re.sub(r"\D", "", phone)
        if digits:
            keys.append(digits)
            if len(digits) > 10:
                keys.append(digits[-10:])
    return list(dict.fromkeys(k for k in keys if k))


def _read_contacts_db(db_path: Path) -> list[PhoneLinkContact]:
    conn = _connect_contacts_db_readonly(db_path)
    if not conn:
        return []
    by_id: dict[int, PhoneLinkContact] = {}
    try:
        cur = conn.execute(
            """
            SELECT c.contact_id, c.display_name, c.nickname, c.given_name,
                   c.middle_name, c.family_name,
                   p.phone_number, p.display_phone_number
            FROM contact c
            LEFT JOIN phonenumber p ON p.contact_id = c.contact_id
            """
        )
        names = [d[0] for d in (cur.description or [])]
        for row in cur.fetchall():
            data = dict(zip(names, row))
            cid = int(data["contact_id"])
            name = _display_name(data)
            if not name or name.lower() in _SKIP_NAMES:
                continue
            phone_raw = str(
                data.get("phone_number") or data.get("display_phone_number") or ""
            )
            phone = normalize_phone(phone_raw) if phone_raw else ""
            rec = by_id.get(cid)
            if not rec:
                rec = PhoneLinkContact(contact_id=cid, name=name, phones=[], match_keys=[])
                by_id[cid] = rec
            if phone and phone not in rec.phones:
                rec.phones.append(phone)
    except sqlite3.Error as exc:
        log.debug("read contacts snapshot failed: %s", exc)
        return []
    finally:
        conn.close()
    out: list[PhoneLinkContact] = []
    for rec in by_id.values():
        rec.match_keys = _build_match_keys(rec.name, rec.phones)
        if rec.name or rec.phones:
            out.append(rec)
    return sorted(out, key=lambda r: r.name.lower())


class PhoneLinkContactIndex:
    """Cached index for resolve + sync. Failures never propagate to callers."""

    def __init__(self, *, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._loaded_at = 0.0
        self._db_path: Path | None = None
        self._db_mtime = 0.0
        self._load_error: str | None = None
        self._by_phone: dict[str, PhoneLinkContact] = {}
        self._by_name: dict[str, PhoneLinkContact] = {}
        self._by_match: dict[str, PhoneLinkContact] = {}
        self._records: list[PhoneLinkContact] = []

    def clear(self) -> None:
        self._loaded_at = 0.0
        self._load_error = None
        self._records.clear()
        self._by_phone.clear()
        self._by_name.clear()
        self._by_match.clear()

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(
        self,
        config: dict[str, Any] | None = None,
        *,
        force: bool = False,
        local_storage: Any | None = None,
    ) -> int:
        try:
            path = resolve_contacts_db_path(config, local_storage=local_storage)
        except Exception as exc:
            log.debug("resolve contacts.db failed: %s", exc)
            self.clear()
            self._load_error = "discovery failed"
            return 0

        if not path or not path.is_file():
            self.clear()
            self._db_path = None
            self._load_error = None
            return 0

        try:
            mtime = path.stat().st_mtime
        except OSError:
            self.clear()
            self._load_error = "unreadable"
            return 0

        now = time.time()
        if (
            not force
            and path == self._db_path
            and mtime == self._db_mtime
            and self._records
            and now - self._loaded_at < self._ttl
        ):
            return len(self._records)

        try:
            records = _read_contacts_db(path)
        except Exception as exc:
            log.debug("contacts index load failed: %s", exc)
            self.clear()
            self._load_error = "read failed"
            return 0

        self._db_path = path
        self._db_mtime = mtime
        self._loaded_at = now
        self._load_error = None
        self._records = records
        self._by_phone.clear()
        self._by_name.clear()
        self._by_match.clear()
        for rec in records:
            key = rec.name.lower()
            self._by_name.setdefault(key, rec)
            for mk in rec.match_keys:
                if mk and not mk.isdigit():
                    self._by_match.setdefault(mk, rec)
            for phone in rec.phones:
                self._by_phone[phone] = rec
                digits = re.sub(r"\D", "", phone)
                if digits:
                    self._by_phone[digits] = rec
                    if len(digits) > 10:
                        self._by_phone[digits[-10:]] = rec
        return len(records)

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    def records(self) -> list[PhoneLinkContact]:
        return list(self._records)

    def by_phone(self, value: str) -> PhoneLinkContact | None:
        phone = normalize_phone(value)
        if not phone:
            digits = re.sub(r"\D", "", value)
            if len(digits) < 7:
                return None
            phone = digits
        rec = self._by_phone.get(phone)
        if rec:
            return rec
        digits = re.sub(r"\D", "", phone)
        if len(digits) > 10:
            return self._by_phone.get(digits[-10:])
        return self._by_phone.get(digits)

    def by_name(self, value: str, *, exact: bool = False) -> PhoneLinkContact | None:
        key = (value or "").strip().lower()
        if not key:
            return None
        if key in self._by_name:
            return self._by_name[key]
        if key in self._by_match:
            return self._by_match[key]
        if exact:
            return None
        for rec in self._records:
            if key in rec.name.lower():
                return rec
        return None

    def match_sender(self, sender: str, body: str = "") -> PhoneLinkContact | None:
        sender = (sender or "").strip()
        body = (body or "").strip()
        if sender:
            if looks_like_phone(sender):
                hit = self.by_phone(sender)
                if hit:
                    return hit
            hit = self.by_name(sender)
            if hit:
                return hit
            sid_digits = re.sub(r"\D", "", sender)
            if len(sid_digits) >= 7:
                hit = self.by_phone(sid_digits)
                if hit:
                    return hit
        if body and sender.lower() in _APP_SENDERS:
            m = _BODY_NAME_RE.match(body)
            if m:
                hint = m.group(1).strip()
                hit = self.by_name(hint, exact=True)
                if hit:
                    return hit
        return None


_index = PhoneLinkContactIndex()


def get_phone_link_contact_index(
    config: dict[str, Any] | None = None,
    *,
    local_storage: Any | None = None,
) -> PhoneLinkContactIndex:
    sync_cfg = (config or {}).get("sync") or {}
    ttl = float((config or {}).get("cache", {}).get("ttl_seconds", 30))
    if sync_cfg.get("import_phone_link_db", True):
        _index._ttl = max(ttl, 30.0)
    ls = local_storage if local_storage is not None else _local_storage(config)
    _index.load(config, local_storage=ls)
    return _index


def lookup_phone_link_contact(
    sender: str,
    body: str = "",
    *,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Return display name from Phone Link contacts.db if recognized."""
    if config and not (config.get("sync") or {}).get("import_phone_link_db", True):
        return None
    try:
        idx = get_phone_link_contact_index(config)
        hit = idx.match_sender(sender, body)
        return hit.name if hit else None
    except Exception as exc:
        log.debug("phone link contact lookup failed: %s", exc)
        return None


def import_phone_link_contacts_from_db(
    *,
    limit: int = 200,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rows for merge_contact_sources — managed=false suggestions."""
    try:
        idx = get_phone_link_contact_index(config)
    except Exception:
        return []
    if not idx.records():
        return []
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    seen_phones: set[str] = set()
    for rec in idx.records():
        if not rec.phones:
            continue
        phone = rec.phones[0]
        if phone in seen_phones:
            continue
        seen_phones.add(phone)
        match = list(rec.match_keys)
        if rec.name.lower() not in match:
            match.insert(0, rec.name.lower())
        out.append(
            {
                "id": str(uuid.uuid4()),
                "name": rec.name,
                "phone": phone,
                "email": "",
                "notes": "Phone Link contacts.db",
                "aliases": [],
                "match": match,
                "platform": "imessage",
                "managed": False,
                "created_at": now,
                "updated_at": now,
                "source": "phone_link:contacts.db",
            }
        )
        if len(out) >= limit:
            break
    return out


# Back-compat alias
find_contacts_databases = discover_contacts_databases
