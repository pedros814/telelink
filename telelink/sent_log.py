"""Outbound SMS log (sent.jsonl) — path, append, and max-entry rotation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DISABLED = frozenset({"", "0", "false", "off", "no", "none", "disabled", "never", "unlimited"})


def sent_log_path(config: dict[str, Any]) -> Path:
    out = config.get("output") or {}
    messaging = config.get("messaging") or {}
    return Path(out.get("dir", "./data")) / messaging.get("sent_log", "sent.jsonl")


def sent_log_max_entries(config: dict[str, Any]) -> int | None:
    """Max lines to keep in sent.jsonl. None = unlimited (rotation off)."""
    messaging = config.get("messaging") or {}
    parsed = messaging.get("sent_log_max_entries")
    if parsed is None:
        parsed = messaging.get("sent_log_max")
    if parsed is None:
        return 5
    if parsed is False:
        return None
    if isinstance(parsed, bool):
        return None
    if isinstance(parsed, (int, float)):
        n = int(parsed)
        return n if n > 0 else None
    text = str(parsed).strip().lower()
    if text in _DISABLED:
        return None
    if text.isdigit():
        n = int(text)
        return n if n > 0 else None
    return None


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    return lines


def prune_sent_log(config: dict[str, Any], *, max_entries: int | None = None) -> int:
    """Drop oldest lines when over limit. Returns number of lines removed."""
    limit = max_entries if max_entries is not None else sent_log_max_entries(config)
    if not limit:
        return 0
    path = sent_log_path(config)
    lines = _read_lines(path)
    if len(lines) <= limit:
        return 0
    removed = len(lines) - limit
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for line in lines[-limit:]:
            f.write(line + "\n")
    return removed


def append_sent_log(config: dict[str, Any], record: dict[str, Any]) -> None:
    """Append one JSON line and rotate oldest entries when over the configured limit."""
    messaging = config.get("messaging") or {}
    if not messaging.get("log_sent", True):
        return
    path = sent_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    prune_sent_log(config)
