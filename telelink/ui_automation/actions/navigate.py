"""Conversation navigation actions for Phone Link UI automation."""

from __future__ import annotations

import re
import time
from typing import Any

from telelink.contacts import dial_digits

try:
    from telelink.ui_automation.config_helpers import get_automation_config
    from telelink.ui_automation.engines.pywinauto_engine import PywinautoEngine
    from telelink.ui_automation.orchestrator import run_action
except Exception:  # pragma: no cover - standalone fallback path
    get_automation_config = None  # type: ignore[assignment]
    PywinautoEngine = None  # type: ignore[assignment]
    run_action = None  # type: ignore[assignment]

from telelink.ui_automation.session import phone_link_title_match as _session_title_match
_SKIP_BODIES = frozenset(
    {
        "messages",
        "conversations",
        "recent",
        "emoji",
        "send",
        "new message",
        "phone link",
    }
)


def phone_link_title_match(title: str) -> bool:
    return _session_title_match(title)


def _digits_key(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def valid_phone_keys(phone_keys: set[str]) -> set[str]:
    return {k for k in phone_keys if len(_digits_key(k)) >= 7}


def read_conversation_header(win) -> tuple[str, str]:
    name = ""
    phone = ""
    try:
        pane = win.child_window(title="Conversation Content", control_type="Group")
    except Exception:
        return "", ""
    for el in pane.descendants(control_type="Text"):
        try:
            text = (el.window_text() or "").strip()
        except Exception:
            continue
        if not text:
            continue
        if re.fullmatch(r"\+\d{1,4}", text.replace(" ", "")):
            continue
        digits = dial_digits(text)
        if digits and len(digits) >= 10 and ("+" in text or "-" in text or "(" in text or len(text) > 10):
            phone = text
            continue
        low = text.lower()
        if low in _SKIP_BODIES or low.startswith("call "):
            continue
        if not name and 1 < len(text) < 80:
            name = text
    return name, phone


def conversation_list(win):
    for el in win.descendants(control_type="List"):
        try:
            aid = getattr(el.element_info, "automation_id", None) or ""
            title = (el.window_text() or "").lower()
            if aid == "CVSListView" or title == "conversations":
                return el
        except Exception:
            continue
    for spec in (
        {"auto_id": "CVSListView", "control_type": "List"},
        {"title": "Conversations", "control_type": "List"},
    ):
        try:
            lst = win.child_window(**spec)
            if lst.exists(timeout=0.5):
                return lst
        except Exception:
            continue
    return None


def header_matches(
    header_name: str,
    header_phone: str,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
) -> bool:
    keys = {_digits_key(k) for k in phone_keys if len(_digits_key(k)) >= 7}
    header_digits = _digits_key(header_phone) or _digits_key(dial_digits(header_phone))
    target_digits = _digits_key(phone) or _digits_key(dial_digits(phone))
    if header_digits and (header_digits in keys or target_digits in header_digits or header_digits in target_digits):
        return True
    aliases = {a.lower() for a in (name_aliases or set()) if str(a).strip()}
    aliases.add((display or "").lower())
    header_name_low = (header_name or "").lower()
    for alias in aliases:
        if not alias:
            continue
        if alias in header_name_low or header_name_low in alias:
            return True
        ascii_alias = re.sub(r"[^\w\s]", "", alias).strip()
        ascii_header = re.sub(r"[^\w\s]", "", header_name_low).strip()
        if ascii_alias and ascii_header and (ascii_alias in ascii_header or ascii_header in ascii_alias):
            return True
    return False


def conversation_list_item_matches(
    text: str,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
) -> bool:
    low = (text or "").lower()
    aliases = {a.lower() for a in (name_aliases or set()) if str(a).strip()}
    aliases.add((display or "").lower())
    aliases = {a for a in aliases if a}

    for alias in aliases:
        ascii_alias = re.sub(r"[^\w\s]", "", alias).strip()
        plain = re.sub(r"[^\w\s]", "", low)
        if alias and alias in low:
            return True
        if ascii_alias and len(ascii_alias) >= 2 and ascii_alias in plain:
            return True

    if low.startswith("conversation with"):
        display_low = (display or "").lower()
        ascii_display = re.sub(r"[^\w\s]", "", display_low).strip()
        if display_low and display_low in low:
            return True
        if ascii_display and len(ascii_display) >= 2 and ascii_display in re.sub(r"[^\w\s]", "", low):
            return True

    keys = {_digits_key(k) for k in phone_keys if len(_digits_key(k)) >= 7}
    digits = _digits_key(text)
    if keys and any(k in digits for k in keys):
        return True
    target_digits = _digits_key(dial_digits(phone))
    if target_digits and target_digits in digits:
        return True
    return False


def ensure_messages_tab(win) -> bool:
    """Click the Messages nav item when Phone Link is on another tab."""
    for spec in (
        {"title_re": r"(?i)^messages$", "control_type": "Button"},
        {"title_re": r"(?i)^messages$", "control_type": "TabItem"},
        {"title_re": r"(?i)^messages$", "control_type": "ListItem"},
        {"title": "Messages", "control_type": "Button"},
    ):
        try:
            btn = win.child_window(**spec)
            if btn.exists(timeout=0.25):
                btn.click_input()
                time.sleep(0.6)
                return True
        except Exception:
            continue
    try:
        for el in win.descendants(control_type="Button"):
            try:
                t = (el.window_text() or "").strip().lower()
                if t == "messages":
                    el.click_input()
                    time.sleep(0.6)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _window_from_session_or_win(session_or_win):
    if session_or_win is None:
        return None
    if hasattr(session_or_win, "descendants") and hasattr(session_or_win, "child_window"):
        return session_or_win
    for attr in ("win", "window", "uia_window"):
        win = getattr(session_or_win, attr, None)
        if win is not None:
            return win
    return None


def _click_target_conversation(
    win,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
) -> dict[str, Any]:
    ensure_messages_tab(win)
    conv = conversation_list(win)
    if conv is None:
        return {"acted": False, "note": "Conversation list not found in Phone Link — open Messages tab"}
    try:
        items = conv.descendants(control_type="ListItem")
    except Exception:
        return {"acted": False, "note": "Conversation list did not expose list items"}
    for item in items:
        try:
            text = item.window_text() or ""
        except Exception:
            continue
        if not conversation_list_item_matches(
            text,
            display=display,
            phone=phone,
            phone_keys=phone_keys,
            name_aliases=name_aliases,
        ):
            continue
        try:
            item.click_input()
            return {"acted": True, "item_text": text, "note": "Clicked matching conversation list row"}
        except Exception:
            continue
    return {
        "acted": False,
        "note": "Target conversation not found in list — open it manually in Phone Link → Messages",
    }


def _verify_header(
    win,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
) -> tuple[bool, str, str]:
    header_name, header_phone = read_conversation_header(win)
    ok = header_matches(
        header_name,
        header_phone,
        display=display,
        phone=phone,
        phone_keys=phone_keys,
        name_aliases=name_aliases,
    )
    return ok, header_name, header_phone


def open_thread(
    session_or_win,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
    engine: str = "pywinauto",
) -> dict[str, Any]:
    win = _window_from_session_or_win(session_or_win)
    if win is None:
        return {
            "ok": False,
            "acted": False,
            "verified": False,
            "engine": engine,
            "note": "Phone Link window handle is missing",
        }

    keys = valid_phone_keys(phone_keys)
    already_ok, header_name, header_phone = _verify_header(
        win,
        display=display,
        phone=phone,
        phone_keys=keys,
        name_aliases=name_aliases,
    )
    if already_ok:
        return {
            "ok": True,
            "acted": False,
            "verified": True,
            "engine": engine,
            "header_name": header_name,
            "header_phone": header_phone,
            "note": "Target thread already focused",
        }

    click_result = _click_target_conversation(
        win,
        display=display,
        phone=phone,
        phone_keys=keys,
        name_aliases=name_aliases,
    )
    if not click_result.get("acted"):
        return {
            "ok": False,
            "acted": False,
            "verified": False,
            "engine": engine,
            "note": str(click_result.get("note") or "Could not click target conversation"),
        }

    time.sleep(0.75)
    verified, new_name, new_phone = _verify_header(
        win,
        display=display,
        phone=phone,
        phone_keys=keys,
        name_aliases=name_aliases,
    )
    if verified:
        return {
            "ok": True,
            "acted": True,
            "verified": True,
            "engine": engine,
            "header_name": new_name,
            "header_phone": new_phone,
            "note": "Opened target conversation in Phone Link",
        }

    return {
        "ok": False,
        "acted": True,
        "verified": False,
        "engine": engine,
        "header_name": new_name,
        "header_phone": new_phone,
        "note": "Clicked conversation but header did not match target contact",
    }


def _open_thread_with_retry(
    session_or_win,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
    engine: str,
    attempts: int = 2,
) -> dict[str, Any]:
    try_count = max(1, int(attempts))
    history: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for idx in range(try_count):
        result = open_thread(
            session_or_win,
            display=display,
            phone=phone,
            phone_keys=phone_keys,
            name_aliases=name_aliases,
            engine=engine,
        )
        history.append(
            {
                "attempt": idx + 1,
                "acted": bool(result.get("acted")),
                "verified": bool(result.get("verified")),
                "ok": bool(result.get("ok")),
                "note": str(result.get("note") or ""),
            }
        )
        if result.get("ok"):
            result["attempts"] = history
            return result
        last_result = result
        if idx + 1 < try_count:
            time.sleep(0.35)
    out = dict(last_result or {"ok": False, "engine": engine, "verified": False})
    out["attempts"] = history
    if not out.get("note"):
        out["note"] = "Could not open target conversation — open it manually in Phone Link → Messages"
    return out


def open_thread_orchestrated(
    session_or_win,
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    name_aliases: set[str] | None = None,
    engine: str = "pywinauto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    win = _window_from_session_or_win(session_or_win)
    if win is None:
        return {
            "ok": False,
            "acted": False,
            "verified": False,
            "engine": engine,
            "note": "Phone Link window handle is missing",
        }

    keys = valid_phone_keys(phone_keys)
    already_ok, header_name, header_phone = _verify_header(
        win,
        display=display,
        phone=phone,
        phone_keys=keys,
        name_aliases=name_aliases,
    )
    if already_ok:
        return {
            "ok": True,
            "acted": False,
            "verified": True,
            "engine": engine,
            "header_name": header_name,
            "header_phone": header_phone,
            "note": "Target thread already focused",
        }

    if callable(run_action) and PywinautoEngine is not None and callable(get_automation_config):
        cfg = config or {}
        auto_cfg = get_automation_config(cfg)
        runner = PywinautoEngine(cfg)
        context: dict[str, Any] = {"win": win}

        def _act(e, ctx: dict[str, Any]) -> bool:
            del e
            target = ctx.get("win")
            if target is None:
                return False
            click_result = _click_target_conversation(
                target,
                display=display,
                phone=phone,
                phone_keys=keys,
                name_aliases=name_aliases,
            )
            ctx["last_click_note"] = click_result.get("note")
            return bool(click_result.get("acted"))

        def _verify(e, ctx: dict[str, Any]) -> tuple[bool, str]:
            del e
            target = ctx.get("win")
            if target is None:
                return False, "window_missing"
            verified, _, _ = _verify_header(
                target,
                display=display,
                phone=phone,
                phone_keys=keys,
                name_aliases=name_aliases,
            )
            return verified, ("header_matches" if verified else "header_mismatch")

        orchestrated = run_action(
            "open_thread",
            _act,
            _verify,
            [runner],
            max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
            context=context,
        )
        header_now, phone_now = read_conversation_header(win)
        orchestrated["header_name"] = header_now
        orchestrated["header_phone"] = phone_now
        orchestrated["engine"] = engine
        if not orchestrated.get("ok"):
            click_note = str(context.get("last_click_note") or "")
            if click_note:
                orchestrated["note"] = click_note
            else:
                orchestrated["note"] = (
                    "Could not open target conversation — open it manually in Phone Link → Messages"
                )
        return orchestrated

    return _open_thread_with_retry(
        win,
        display=display,
        phone=phone,
        phone_keys=keys,
        name_aliases=name_aliases,
        engine=engine,
        attempts=2,
    )

