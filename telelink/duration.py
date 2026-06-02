from __future__ import annotations

import re
from typing import Any

_DURATION_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?\s*$",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}

_DISABLED = frozenset({"", "0", "false", "off", "no", "none", "disabled", "never"})


def parse_duration(value: Any) -> int | None:
    """Parse config TTL. None means caught messages never expire."""
    if value is None or value is False:
        return None
    if isinstance(value, (int, float)):
        seconds = int(value)
        return seconds if seconds > 0 else None
    if isinstance(value, bool):
        return None
    text = str(value).strip().lower()
    if text in _DISABLED:
        return None
    if text.isdigit():
        seconds = int(text)
        return seconds if seconds > 0 else None
    m = _DURATION_RE.match(text)
    if not m:
        return None
    amount = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    mult = _UNIT_SECONDS.get(unit, 1)
    seconds = int(amount * mult)
    return seconds if seconds > 0 else None


def format_duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
