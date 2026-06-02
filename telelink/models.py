from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class AttachmentMeta:
    path: str
    filename: str = ""
    media_kind: str = "image"  # image | screenshot | unknown
    mime_type: str = ""
    size_bytes: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MessageEvent:
    """Internal event from notifications or folder watcher."""

    sender_display: str
    body: str
    source: str = "phone_link"  # phone_link | folder_watch | manual
    notification_app: str = ""
    watch_folder: str = ""
    file_path: Path | None = None


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contact: str = ""
    task: str = ""
    raw_message: str = ""
    priority: str = "medium"
    type: str = "request"
    platform: str = ""
    source: str = "phone_link"
    sender: str = ""
    sender_id: str = ""
    channel: str = "unknown"  # imessage | sms | instagram | facebook | system | other
    message_kind: str = "text"  # text | image | screenshot
    contact_matched: bool = False
    notification_app: str = ""
    watch_folder: str = ""
    attachments: list[str] = field(default_factory=list)
    attachment_meta: list[dict[str, Any]] = field(default_factory=list)
    detected_keywords: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now_iso)
    ocr_text: str = ""
    correlated_from: str = ""  # sender_id of linked text message, if image was matched

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
