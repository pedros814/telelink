"""Send SMS/text via Phone Link, UI auto-send, or Android adb."""

from __future__ import annotations

import re
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from telelink.classify import get_owner
from telelink.contacts import ContactStore, dial_digits, dial_phone, looks_like_phone, normalize_phone

# @tag in outgoing SMS → owner.* in config.yaml (case-insensitive tag)
_OWNER_TAG_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("personal_name_short", ("nameshort", "name_short", "short")),
    ("personal_name_full", ("namefull", "name_full", "fullname", "full")),
    ("business_name", ("business",)),
    ("work_email", ("email",)),
    ("timezone", ("timezone",)),
    ("talking_tone", ("tone", "talkingtone", "talking_tone")),
]

_OWNER_TAG_LABELS: dict[str, str] = {
    "personal_name_short": "Short name",
    "personal_name_full": "Full name",
    "business_name": "Business",
    "work_email": "Email",
    "timezone": "Timezone",
    "talking_tone": "Talking tone",
}


def _owner_tag_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for config_key, tags in _OWNER_TAG_GROUPS:
        for tag in tags:
            lookup[tag.lower()] = config_key
    return lookup


_OWNER_TAG_KEYS = _owner_tag_lookup()


def owner_send_tag_help() -> list[tuple[str, str, str]]:
    """(tags_display, config.yaml key, description) for how-to / help tables."""
    rows: list[tuple[str, str, str]] = []
    for config_key, tags in _OWNER_TAG_GROUPS:
        primary = f"@{tags[0]}"
        aliases = ", ".join(f"@{t}" for t in tags[1:])
        tags_display = primary if not aliases else f"{primary}, {aliases}"
        rows.append((tags_display, config_key, _OWNER_TAG_LABELS.get(config_key, config_key)))
    return rows

_TAG_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]*)")
# Spaced /n — trim surrounding whitespace (agent-friendly).
_NEWLINE_SPACED_RE = re.compile(r"\s+/n\s+", re.IGNORECASE)
# Tight /n runs (e.g. ./n/nWHAT) — one pass so /n/n is not blocked by the first n.
_NEWLINE_TIGHT_RUN_RE = re.compile(r"(?<![/\w])(?:/n)+", re.IGNORECASE)


def _expand_newlines(text: str) -> str:
    """Turn /n and literal \\n into real newlines; avoid breaking URLs."""
    if not text:
        return text
    text = text.replace("\\n", "\n")
    text = _NEWLINE_SPACED_RE.sub("\n", text)

    def _tight_run(match: re.Match[str]) -> str:
        count = len(re.findall(r"/n", match.group(0), flags=re.IGNORECASE))
        return "\n" * count

    text = _NEWLINE_TIGHT_RUN_RE.sub(_tight_run, text)
    return text


def expand_message_body(body: str, config: dict[str, Any] | None) -> str:
    """Expand @owner tags and /n newlines before send."""
    text = body or ""
    if not text:
        return text

    owner = get_owner(config or {})

    def _replace_tag(match: re.Match[str]) -> str:
        key = _OWNER_TAG_KEYS.get(match.group(1).lower())
        if not key:
            return match.group(0)
        val = owner.get(key)
        if val is None or str(val).strip() == "":
            return match.group(0)
        return str(val)

    text = _TAG_RE.sub(_replace_tag, text)
    text = _expand_newlines(text)
    return text


def send_message(
    to_phone: str,
    body: str,
    *,
    config: dict[str, Any] | None = None,
    contact_name: str = "",
    raw: bool = False,
) -> dict[str, Any]:
    phone = normalize_phone(to_phone)
    if not phone or not looks_like_phone(phone):
        raise ValueError(f"invalid phone number: {to_phone!r} (use +number, not a contact name)")
    dial = dial_digits(phone)
    if len(dial) < 10:
        raise ValueError(f"invalid phone number: {to_phone!r}")
    text = (body or "").strip() if raw else expand_message_body(body or "", config).strip()
    if not text:
        raise ValueError("message body is empty")

    method = "sms_uri"
    if config:
        method = str(config.get("messaging", {}).get("method", "sms_uri")).lower()

    if method in ("auto", "phone_link_auto"):
        from telelink.messaging_auto import auto_send_phone_link

        result = auto_send_phone_link(phone, text, config=config)
    elif method == "adb":
        from telelink.messaging_adb import send_via_adb

        result = send_via_adb(phone, text, config=config or {})
    else:
        uri = f"sms:{dial}?body={quote(text)}"
        opened = _open_uri(uri, method=method)
        result = {
            "method": method,
            "uri": uri,
            "opened": opened,
            "auto_sent": False,
            "note": "Compose opened — tap Send in Phone Link",
        }

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to_phone": phone,
        "dial": dial,
        "to_name": contact_name or phone,
        "body": text,
        **result,
    }
    if config:
        _log_sent(config, record)
    return record


def _open_uri(uri: str, *, method: str) -> bool:
    if method == "browser":
        return webbrowser.open(uri)
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", uri],
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
            return True
        except OSError:
            return webbrowser.open(uri)
    return webbrowser.open(uri)


def _log_sent(config: dict[str, Any], record: dict[str, Any]) -> None:
    from telelink.sent_log import append_sent_log

    append_sent_log(config, record)


def resolve_send_recipient(
    target: str,
    *,
    store: ContactStore,
) -> tuple[str, str]:
    """Resolve name or +number to (dialable_phone, display_label). Phone Link needs digits."""
    from telelink.contacts import clean_send_target, dial_phone

    raw = clean_send_target((target or "").strip())
    if not raw:
        raise ValueError("missing contact name or phone number")
    if looks_like_phone(raw):
        phone = normalize_phone(raw)
        return phone, phone

    resolved = store.resolve(raw)
    contact = resolved.get("contact")
    phone = dial_phone(contact) if contact else ""
    if not phone:
        phone = str(resolved.get("phone") or "")
    if not phone or not looks_like_phone(phone):
        label = str(resolved.get("name") or target)
        raise ValueError(
            f"contact '{label}' has no dialable phone number — use +number or contacts add"
        )
    display = str(resolved.get("name") or target)
    return normalize_phone(phone), display


def send_to_target(
    target: str,
    body: str,
    *,
    store: ContactStore,
    config: dict[str, Any],
    raw: bool = False,
) -> dict[str, Any]:
    phone, display = resolve_send_recipient(target, store=store)
    return send_message(
        phone,
        body,
        config=config,
        contact_name=display,
        raw=raw,
    )
