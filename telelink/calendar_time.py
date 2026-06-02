"""Parse natural and relative schedule times for the calendar layer."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_IN_RE = re.compile(
    r"^\s*in\s+(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?\s*$",
    re.IGNORECASE,
)
_AT_RE = re.compile(
    r"^\s*(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*$",
    re.IGNORECASE,
)
_DAY_WORDS = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "tmr": 1,
    "tmrw": 1,
}

_GLUED_DURATION_RE = re.compile(
    r"^(\d+(?:\.\d+)?)(hours?|hrs?|h|minutes?|mins?|minute|m|seconds?|secs?|sec|s|days?|day|d)$",
    re.IGNORECASE,
)
_UNIT_SHORT = {
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "hrs": "h",
    "h": "h",
    "minute": "m",
    "minutes": "m",
    "min": "m",
    "mins": "m",
    "m": "m",
    "second": "s",
    "seconds": "s",
    "sec": "s",
    "secs": "s",
    "s": "s",
    "day": "d",
    "days": "d",
    "d": "d",
}


def normalize_when_expression(raw: str) -> str:
    """Turn 2hour / 30min into forms parse_fire_at understands."""
    s = (raw or "").strip()
    if not s:
        return s
    if s.lower().startswith("in "):
        return s
    compact = s.replace(" ", "")
    m = _GLUED_DURATION_RE.match(compact)
    if m:
        amount, unit = m.group(1), m.group(2).lower()
        short = _UNIT_SHORT.get(unit, unit)
        return f"in {amount}{short}"
    return s


def owner_timezone(config: dict[str, Any] | None) -> ZoneInfo | timezone:
    tz_name = ""
    if config:
        tz_name = str((config.get("owner") or {}).get("timezone") or "").strip()
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    local = datetime.now().astimezone().tzinfo
    if local is not None:
        return local
    return timezone.utc


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_fire_at(dt: datetime) -> str:
    return _utc(dt).isoformat()


def parse_fire_at(
    text: str,
    *,
    config: dict[str, Any] | None = None,
    base: datetime | None = None,
) -> datetime:
    """Parse when an event should fire. Raises ValueError on failure."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("schedule time is required")

    tz = owner_timezone(config)
    now_local = (base or datetime.now(timezone.utc)).astimezone(tz)

    # ISO 8601
    try:
        iso = raw.replace("Z", "+00:00")
        if "T" in iso or re.match(r"^\d{4}-\d{2}-\d{2}", iso):
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            if _utc(dt) <= datetime.now(timezone.utc):
                if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
                    dt = dt.replace(hour=now_local.hour, minute=now_local.minute)
            return _utc(dt)
    except (TypeError, ValueError):
        pass

    lower = raw.lower()

    m_in = _IN_RE.match(lower)
    if m_in:
        amount = m_in.group(1)
        unit = m_in.group(2) or "m"
        from telelink.duration import parse_duration

        secs = parse_duration(f"{amount}{unit}")
        if not secs:
            raise ValueError(f"could not parse duration: {text!r}")
        return _utc(now_local + timedelta(seconds=secs))

    # duration-only: 30m, 2h (delay shorthand)
    from telelink.duration import parse_duration

    secs = parse_duration(lower)
    if secs:
        return _utc(now_local + timedelta(seconds=secs))

    # strip leading "at"
    phrase = lower
    if phrase.startswith("at "):
        phrase = phrase[3:].strip()

    day_offset = 0
    for word, off in _DAY_WORDS.items():
        if phrase == word:
            day_offset = off
            phrase = ""
            break
        if phrase.startswith(word + " "):
            day_offset = off
            phrase = phrase[len(word) :].strip()
            break
        if phrase.endswith(" " + word):
            day_offset = off
            phrase = phrase[: -len(word)].strip()
            break

    # "2pm today" / "today 2pm" / "tomorrow 9:30 am"
    time_part = phrase
    for word in _DAY_WORDS:
        time_part = re.sub(rf"\b{word}\b", "", time_part).strip()

    m_at = _AT_RE.match(time_part) if time_part else None
    if not m_at:
        raise ValueError(
            f"could not parse schedule time: {text!r} — try 2pm today, in 3h, tomorrow 9am, or 2026-05-28T14:00"
        )

    hour = int(m_at.group(1))
    minute = int(m_at.group(2) or 0)
    ampm = (m_at.group(3) or "").lower().replace(".", "")
    if ampm in ("pm", "p") and hour < 12:
        hour += 12
    elif ampm in ("am", "a") and hour == 12:
        hour = 0
    elif not ampm and hour <= 12 and hour < now_local.hour - 1:
        # bare hour without am/pm — if already passed today, assume pm for 1-11
        if 1 <= hour <= 11:
            hour += 12

    target = (now_local + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if day_offset == 0 and target <= now_local:
        target += timedelta(days=1)
    return _utc(target)


def format_local_short(dt: datetime, *, config: dict[str, Any] | None = None) -> str:
    tz = owner_timezone(config)
    local = _utc(dt).astimezone(tz)
    return local.strftime("%Y-%m-%d %H:%M %Z").replace("  ", " ")


def format_relative_until(dt: datetime) -> str:
    from telelink.duration import format_duration

    seconds = int((_utc(dt) - datetime.now(timezone.utc)).total_seconds())
    if seconds < 0:
        return "overdue"
    if seconds < 60:
        return "under 1m"
    return f"in {format_duration(seconds)}"
