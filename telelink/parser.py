from __future__ import annotations

import re
from typing import Any

from telelink.classify import classify_channel, normalize_sender_id, resolve_contact
from telelink.models import AttachmentMeta, Task, utc_now_iso

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
SHOPIFY_RE = re.compile(r"shopify|myshopify", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-_/]+", re.IGNORECASE)
IMAGE_IN_TEXT_RE = re.compile(
    r"\b(sent a photo|sent an image|sent a picture|attached an image|image attachment|📷|🖼)\b",
    re.IGNORECASE,
)


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text or "")


def summarize_task(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return "New message"
    first = re.split(r"[.!?\n]", cleaned, maxsplit=1)[0].strip()
    if len(first) <= max_len:
        return first
    return first[: max_len - 3].rstrip() + "..."


def muted_words(config: dict[str, Any]) -> list[str]:
    return list(config.get("parser", {}).get("muted_words", []) or [])


def urgent_words(config: dict[str, Any]) -> list[str]:
    return list(config.get("parser", {}).get("urgent_words", []) or [])


def is_muted_message(text: str, config: dict[str, Any]) -> bool:
    """Negative parser — message matches any muted_words (skip watcher / caught)."""
    lower = (text or "").lower()
    return any(w.lower() in lower for w in muted_words(config) if str(w).strip())


def detect_keywords(text: str, config: dict[str, Any]) -> list[str]:
    lower = (text or "").lower()
    found: list[str] = []
    groups = {
        "urgent": urgent_words(config),
    }
    for label, words in groups.items():
        for w in words:
            if w.lower() in lower and w.lower() not in found:
                found.append(w.lower())
        if label not in found and any(w.lower() in lower for w in words):
            found.append(label)
    for token in WORD_RE.findall(text or ""):
        t = token.lower()
        if len(t) >= 5 and t not in found and t in lower:
            if any(
                k in t
                for k in (
                    "checkout",
                    "navbar",
                    "mobile",
                    "header",
                    "footer",
                    "cart",
                    "product",
                    "theme",
                    "spacing",
                    "align",
                )
            ):
                found.append(t)
    return found[:20]


def infer_priority(text: str, config: dict[str, Any]) -> str:
    lower = (text or "").lower()
    if any(w.lower() in lower for w in urgent_words(config)):
        return "high"
    if any(w in lower for w in ("when you can", "low priority", "no rush")):
        return "low"
    return "medium"


def infer_type(text: str, config: dict[str, Any]) -> str:
    del text, config
    return "request"


def infer_platform(text: str) -> str:
    if SHOPIFY_RE.search(text or ""):
        return "shopify"
    if "wordpress" in (text or "").lower():
        return "wordpress"
    if "react" in (text or "").lower() or "next.js" in (text or "").lower():
        return "web"
    return ""


def infer_message_kind(
    message: str,
    attachments: list[AttachmentMeta],
    ocr_text: str = "",
) -> str:
    if attachments:
        kinds = {a.media_kind for a in attachments}
        if "screenshot" in kinds:
            return "screenshot"
        return "image"
    if IMAGE_IN_TEXT_RE.search(message or ""):
        return "image"
    if ocr_text.strip():
        return "screenshot"
    return "text"


def build_task(
    *,
    config: dict[str, Any],
    message: str,
    sender: str = "",
    attachments: list[AttachmentMeta] | None = None,
    ocr_text: str = "",
    source: str = "phone_link",
    channel: str | None = None,
    message_kind: str | None = None,
    contact_matched: bool | None = None,
    contact: str | None = None,
    contact_store=None,
    notification_app: str = "",
    watch_folder: str = "",
    correlated_from: str = "",
) -> Task:
    att_list = attachments or []
    sender_display = (sender or "").strip()
    sender_id = normalize_sender_id(sender_display)
    ch = channel or classify_channel(sender_display, message)
    resolved_contact, matched = resolve_contact(
        config, sender_display, message, store=contact_store
    )
    contact_name = contact if contact is not None else resolved_contact
    matched_flag = contact_matched if contact_matched is not None else matched
    combined = "\n".join(filter(None, [message, ocr_text]))
    kind = message_kind or infer_message_kind(message, att_list, ocr_text)

    return Task(
        contact=contact_name,
        task=summarize_task(combined),
        raw_message=message,
        priority=infer_priority(combined, config),
        type=infer_type(combined, config),
        platform=infer_platform(combined),
        source=source,
        sender=sender_display,
        sender_id=sender_id,
        channel=ch,
        message_kind=kind,
        contact_matched=matched_flag,
        notification_app=notification_app,
        watch_folder=watch_folder,
        attachments=[a.path for a in att_list],
        attachment_meta=[a.to_dict() for a in att_list],
        detected_keywords=detect_keywords(combined, config),
        urls=extract_urls(combined),
        timestamp=utc_now_iso(),
        ocr_text=ocr_text.strip(),
        correlated_from=correlated_from,
    )
