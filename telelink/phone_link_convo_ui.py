"""Read visible SMS/iMessage thread from Phone Link UI when phone.db is absent (common on iPhone)."""

from __future__ import annotations

import sys
import time
from typing import Any

from telelink.ui_automation.actions import navigate as navigate_actions
from telelink.ui_automation.actions import read as read_actions
from telelink.ui_automation.session import (
    UiAutomationSession,
    find_phone_link_window,
    launch_phone_link,
    open_sms_thread_uri,
)


def _name_aliases_for_contact(
    display: str,
    phone_keys: set[str],
    *,
    config: dict[str, Any] | None = None,
    target: str = "",
) -> set[str]:
    aliases: set[str] = {display, target}
    for key in phone_keys:
        if key and not key.isdigit():
            aliases.add(str(key))
    if config:
        try:
            from telelink.session import get_session

            store = get_session().contact_store
            for row in store.list_contacts():
                phone = str(row.get("phone") or "")
                name = str(row.get("name") or "")
                if display.lower() in name.lower() or name.lower() in display.lower():
                    aliases.add(name)
                    for m in row.get("match") or []:
                        aliases.add(str(m))
                    break
        except Exception:
            pass
    return {a.strip() for a in aliases if a and str(a).strip()}


def read_conversation_from_ui(
    *,
    display: str,
    phone: str,
    phone_keys: set[str],
    limit: int = 50,
    navigate: bool = True,
    config: dict[str, Any] | None = None,
    target: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """
    Read the visible thread from Phone Link Messages UI.
    Returns (rows, status_note).
    """
    try:
        import pywinauto  # noqa: F401
    except ImportError:
        return [], "pywinauto not installed — pip install pywinauto"

    cfg = config or {}
    convo_cfg = cfg.get("convo") or {}
    auto_launch = convo_cfg.get("auto_launch_phone_link", True) is not False
    auto_open_uri = convo_cfg.get("auto_open_sms_uri", True) is not False
    launch_wait = float(convo_cfg.get("launch_wait_seconds", 4))
    uri_wait = float(convo_cfg.get("sms_uri_wait_seconds", 2.5))

    session = UiAutomationSession()
    aliases = _name_aliases_for_contact(display, phone_keys, config=cfg, target=target)

    shell_hwnd = None
    if sys.platform == "win32":
        from telelink.win_console import get_console_hwnd

        shell_hwnd = get_console_hwnd()

    win = find_phone_link_window(session=session, config=cfg, timeout_s=0.5)
    if win is None and auto_launch:
        launch_phone_link(config=cfg, wait_s=launch_wait)
        win = find_phone_link_window(session=session, config=cfg, timeout_s=launch_wait)
    if win is None:
        return [], "Phone Link is not open — launch Phone Link → Messages"

    try:
        try:
            win.set_focus()
        except Exception:
            pass

        keys = navigate_actions.valid_phone_keys(phone_keys)
        navigate_actions.ensure_messages_tab(win)

        if navigate and auto_open_uri and phone:
            open_sms_thread_uri(phone)
            time.sleep(max(0.5, uri_wait))
            win = find_phone_link_window(session=session, config=cfg, timeout_s=2.0) or win
            try:
                win.set_focus()
            except Exception:
                pass

        header_name, header_phone = navigate_actions.read_conversation_header(win)
        if navigate_actions.header_matches(
            header_name,
            header_phone,
            display=display,
            phone=phone,
            phone_keys=keys,
            name_aliases=aliases,
        ):
            rows = read_actions.extract_messages(win, peer_name=header_name or display, limit=limit)
            if rows:
                return rows, "phone_link_ui (visible messages — iPhone does not write phone.db locally)"

        if navigate:
            open_thread_fn = getattr(navigate_actions, "open_thread_orchestrated", None)
            if callable(open_thread_fn):
                nav_result = open_thread_fn(
                    win,
                    display=display,
                    phone=phone,
                    phone_keys=keys,
                    name_aliases=aliases,
                    engine="pywinauto",
                    config=cfg,
                )
            else:
                nav_result = navigate_actions.open_thread(
                    win,
                    display=display,
                    phone=phone,
                    phone_keys=keys,
                    name_aliases=aliases,
                    engine="pywinauto",
                )
            if not nav_result.get("ok"):
                rows = read_actions.extract_messages(win, peer_name=display, limit=limit)
                if rows:
                    return rows, "phone_link_ui (visible messages — iPhone does not write phone.db locally)"
                note = str(nav_result.get("note") or "").strip()
                return [], note or (
                    "open the thread in Phone Link → Messages first, or leave Phone Link on that contact"
                )

        header_name, _ = navigate_actions.read_conversation_header(win)
        peer = header_name or display
        rows = read_actions.extract_messages(win, peer_name=peer, limit=limit)
        if not rows:
            return [], "thread open in Phone Link but no MessageBody nodes found — scroll the thread"
        return rows, "phone_link_ui (visible messages — iPhone does not write phone.db locally)"
    finally:
        if sys.platform == "win32":
            from telelink.win_console import handoff_to_shell

            handoff_to_shell(uia_window=win, shell_hwnd=shell_hwnd, settle_ms=150)
