"""Shared send verification predicates for Phone Link UI automation."""

from __future__ import annotations

from telelink.ui_automation.locators import COMPOSE_CONTROL_TYPES, FAILURE_PATTERNS
from telelink.ui_automation.verify.runner import run_verify


def _normalize_body_for_match(text: str) -> str:
    return " ".join((text or "").split()).lower()[:500]


def _get_compose_text(win) -> str:
    """Best-effort read of Phone Link message compose content."""
    parts: list[str] = []
    for ctrl_type in COMPOSE_CONTROL_TYPES:
        try:
            for el in win.descendants(control_type=ctrl_type):
                try:
                    t = (el.window_text() or "").strip()
                    if not t:
                        try:
                            t = (el.get_value() or "").strip()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if t:
                        parts.append(t)
                except Exception:
                    continue
        except Exception:
            continue
    if not parts:
        return ""
    return max(parts, key=len)


def _compose_still_has_body(win, expected_body: str) -> bool:
    text = _get_compose_text(win)
    if not text.strip():
        return False
    exp = _normalize_body_for_match(expected_body)
    got = _normalize_body_for_match(text)
    if not exp:
        return True
    if exp in got or got in exp:
        return True
    if len(exp) >= 20 and exp[:20] in got:
        return True
    if len(got) >= 20 and got[:20] in exp:
        return True
    return bool(got)


def _ui_shows_send_failure(win) -> bool:
    try:
        for el in win.descendants():
            try:
                t = (el.window_text() or "").lower()
                if t and any(p in t for p in FAILURE_PATTERNS):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _thread_has_outgoing_bubble(win, body: str) -> bool:
    exp = _normalize_body_for_match(body)
    if not exp or len(exp) < 3:
        return False
    needle = exp[:80]
    short = needle[:15] if len(needle) >= 15 else needle
    try:
        for ctrl_type in ("ListItem", "Text", "Group"):
            try:
                for el in win.descendants(control_type=ctrl_type):
                    try:
                        t = _normalize_body_for_match(el.window_text() or "")
                        if not t:
                            continue
                        if needle in t or (short and short in t):
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass
    return False


def verify_send_delivered(
    win,
    body: str,
    timeout_ms: int,
    poll_ms: int,
) -> tuple[bool, str]:
    """Poll Phone Link UI for send success/failure signals."""

    def _probe() -> tuple[bool, str]:
        if _ui_shows_send_failure(win):
            return False, "failure_indicator"
        if not _compose_still_has_body(win, body):
            return True, "compose_empty"
        if _thread_has_outgoing_bubble(win, body):
            return True, "thread_bubble"
        return False, "pending"

    return run_verify(_probe, timeout_ms=timeout_ms, poll_ms=poll_ms)
