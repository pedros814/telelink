from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from telelink.contacts import ContactStore

PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{7,}$")
INSTAGRAM_HINTS = ("instagram", "[galore_", "sent a reel", "sent a post")
FACEBOOK_HINTS = ("facebook", "friend suggestion")
SYSTEM_HINTS = (
    "low battery",
    "charge it to stay connected",
    "storage almost full",
    "software update",
    "icloud",
    "airpods",
)


def normalize_sender_id(sender: str) -> str:
    s = (sender or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 7:
        return digits[-10:] if len(digits) > 10 else digits
    return s.lower()


def classify_channel(sender: str, body: str) -> str:
    combined = f"{sender} {body}".lower()
    if any(h in combined for h in INSTAGRAM_HINTS):
        return "instagram"
    if any(h in combined for h in FACEBOOK_HINTS):
        return "facebook"
    if any(h in combined for h in SYSTEM_HINTS):
        return "system"
    if PHONE_RE.match((sender or "").strip()):
        return "imessage"
    if sender and re.search(r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}", sender):
        return "sms"
    if "messages" in combined or "imessage" in combined:
        return "imessage"
    return "other"


def get_owner(config: dict[str, Any]) -> dict[str, Any]:
    """Operator identity (you / your agency) — not a contact."""
    return config.get("owner") or {}


def unmatched_contact_label(config: dict[str, Any]) -> str:
    """Label for notifications that did not match a managed contact."""
    routing = config.get("routing") or {}
    label = routing.get("unmatched_label")
    if label is not None and str(label).strip():
        return str(label).strip()
    return "unassigned"


unmatched_client_label = unmatched_contact_label


def resolve_contact(
    config: dict[str, Any],
    sender: str,
    body: str,
    *,
    store: "ContactStore | None" = None,
) -> tuple[str, bool]:
    """Match notification to a managed contact in contacts.jsonl. Returns (label, matched)."""
    from telelink.contacts import ContactStore, dial_phone, looks_like_phone, normalize_phone

    hay = f"{sender}\n{body}".lower()
    sender_id = normalize_sender_id(sender)

    if store is None:
        try:
            from telelink.session import get_session

            store = get_session().contact_store
        except Exception:
            path = config.get("output", {}).get("contacts_file")
            if path:
                store = ContactStore(path)

    if store:
        cache = getattr(store, "_cache", None)
        if cache is not None:
            rows = cache.get_or_set(
                "contacts:managed",
                lambda: [r for r in store.list_contacts() if r.get("managed") is not False],
            )
        else:
            rows = store.list_contacts()
        for row in rows:
            if row.get("managed") is False:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue

            patterns = list(row.get("match") or [])
            phone = dial_phone(row)
            if phone:
                patterns.append(phone)
                patterns.append(re.sub(r"\D", "", phone))

            for pat in patterns:
                if not pat:
                    continue
                pat_l = str(pat).lower().strip()
                if pat_l in hay or pat_l in sender.lower():
                    return name, True
                pat_digits = re.sub(r"\D", "", pat_l)
                if pat_digits and len(pat_digits) >= 7 and pat_digits == sender_id:
                    return name, True

    # Phone Link contacts.db (iPhone address book on PC)
    sync_cfg = config.get("sync") or {}
    if sync_cfg.get("import_phone_link_db", True):
        from telelink.phone_link_contacts import lookup_phone_link_contact

        pl_name = lookup_phone_link_contact(sender, body, config=config)
        if pl_name:
            return pl_name, False

    # Legacy config clients block (imported into contacts on load)
    clients = config.get("clients") or []
    for entry in clients:
        name = entry.get("name", "")
        for pat in entry.get("match") or []:
            if not pat:
                continue
            pat_l = str(pat).lower()
            if pat_l in hay or pat_l in sender.lower():
                return name, True
            pat_digits = re.sub(r"\D", "", pat_l)
            if pat_digits and pat_digits == sender_id:
                return name, True

    return unmatched_contact_label(config), False


# Back-compat alias
resolve_client = resolve_contact


def should_ingest(
    config: dict[str, Any],
    channel: str,
    contact_matched: bool,
    *,
    message: str = "",
) -> bool:
    from telelink.parser import is_muted_message

    routing = config.get("routing") or {}
    only = routing.get("only_contacts", routing.get("only_clients", False))
    if only and not contact_matched:
        return False
    ignore = {c.lower() for c in routing.get("ignore_channels", [])}
    if channel.lower() in ignore:
        return False
    if is_muted_message(message, config):
        return False
    return True


def sender_hint_from_path(path: Path) -> str:
    skip = {
        "photos",
        "images",
        "phone link",
        "cross device",
        "downloads",
        "attachments",
        "cache",
        "localstate",
        "iphone",
    }
    for part in reversed(path.parts[:-1]):
        low = part.lower()
        if low in skip or part.startswith("."):
            continue
        if re.match(r"^[\d\+\-\(\)\s]+$", part):
            return part.strip()
        if len(part) >= 2:
            return part
    return ""


def classify_media_kind(path: Path, ocr_text: str = "") -> str:
    name = path.name.lower()
    if "screenshot" in name or "screen shot" in name or "screen_shot" in name:
        return "screenshot"
    if name.startswith("img_") and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        try:
            from PIL import Image

            with Image.open(path) as img:
                w, h = img.size
                if w and h and max(w, h) / max(min(w, h), 1) < 2.2:
                    if max(w, h) >= 800:
                        return "screenshot"
        except Exception:
            pass
    if path.suffix.lower() == ".png" and not name.startswith("photo"):
        return "screenshot"
    return "image"
