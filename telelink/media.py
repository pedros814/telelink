from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telelink.classify import classify_media_kind
from telelink.models import AttachmentMeta


def _slug(value: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", (value or "unknown").strip())[:48]
    return s or "unknown"


def build_attachment_meta(path: Path, media_kind: str | None = None) -> AttachmentMeta:
    kind = media_kind or classify_media_kind(path)
    meta = AttachmentMeta(
        path=str(path.resolve()),
        filename=path.name,
        media_kind=kind,
        size_bytes=path.stat().st_size if path.exists() else 0,
    )
    try:
        from PIL import Image

        with Image.open(path) as img:
            meta.width, meta.height = img.size
            meta.mime_type = Image.MIME.get(img.format, "")
    except Exception:
        pass
    return meta


def store_attachment(
    src: Path,
    config: dict[str, Any],
    *,
    contact: str,
    channel: str,
    sender_id: str,
) -> AttachmentMeta:
    base = Path(config["output"]["attachments_dir"])
    media_cfg = config.get("media", {})
    kind = classify_media_kind(src)

    if media_cfg.get("organize_by_sender", True):
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sub = _slug(contact)
        if sender_id:
            sub = f"{sub}_{sender_id[-4:]}" if len(sender_id) >= 4 else sub
        folder_kind = "screenshots" if kind == "screenshot" else "images"
        dest_dir = base / sub / channel / folder_kind / date
    else:
        dest_dir = base

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        stem, suffix = src.stem, src.suffix
        dest = dest_dir / f"{stem}_{int(datetime.now().timestamp())}{suffix}"

    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    else:
        dest = src

    return build_attachment_meta(dest, kind)
