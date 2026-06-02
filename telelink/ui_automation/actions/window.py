"""Window-focused actions (unfocus/minimize) through orchestrator."""

from __future__ import annotations

import time
from typing import Any

from telelink.ui_automation.config_helpers import get_automation_config
from telelink.ui_automation.engines.pywinauto_engine import PywinautoEngine
from telelink.ui_automation.orchestrator import run_action
from telelink.ui_automation.session import UiAutomationSession


def _window_is_minimized(win: Any) -> bool:
    try:
        if hasattr(win, "is_minimized"):
            if bool(win.is_minimized()):
                return True
    except Exception:
        pass
    try:
        state = win.get_show_state()
        if str(state).lower() == "minimized" or int(state) == 2:
            return True
    except Exception:
        pass
    try:
        import ctypes

        hwnd = int(getattr(win, "handle"))
        return bool(ctypes.windll.user32.IsIconic(hwnd))
    except Exception:
        return False


def unfocus_compose_orchestrated(
    config: dict[str, Any],
    session: UiAutomationSession,
) -> dict[str, Any]:
    auto_cfg = get_automation_config(config)
    engine = PywinautoEngine(config)
    context: dict[str, Any] = {"win": session.pywinauto_window}

    def _act(e, ctx: dict[str, Any]) -> bool:
        win = ctx.get("win") or e.find_phone_link_window(session=session)
        if win is None:
            return True
        ctx["win"] = win
        return bool(e.unfocus_compose(win))

    def _verify(e, ctx: dict[str, Any]) -> tuple[bool, str]:
        del e, ctx
        return True, "soft_ok"

    return run_action(
        "unfocus_compose",
        _act,
        _verify,
        [engine],
        max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
        context=context,
    )


def _minimize_with_session(
    config: dict[str, Any],
    session: UiAutomationSession,
) -> dict[str, Any]:
    auto_cfg = get_automation_config(config)
    engine = PywinautoEngine(config)
    context: dict[str, Any] = {"win": session.pywinauto_window}

    def _act(e, ctx: dict[str, Any]) -> bool:
        win = ctx.get("win") or e.find_phone_link_window(session=session)
        if win is None:
            return False
        ctx["win"] = win
        return bool(e.minimize_window(win))

    def _verify(e, ctx: dict[str, Any]) -> tuple[bool, str]:
        del e
        win = ctx.get("win")
        if win is None:
            return False, "window_missing"
        time.sleep(0.1)
        return _window_is_minimized(win), "minimized"

    return run_action(
        "minimize_window",
        _act,
        _verify,
        [engine],
        max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
        context=context,
    )


def _minimize_direct(
    win: Any,
    *,
    settle_ms: int = 150,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    auto_cfg = get_automation_config(cfg)
    engine = PywinautoEngine(cfg)
    context: dict[str, Any] = {"win": win, "settled": False}

    def _act(e, ctx: dict[str, Any]) -> bool:
        target = ctx.get("win")
        if target is None:
            return False
        if not ctx.get("settled") and settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        ctx["settled"] = True
        return bool(e.minimize_window(target))

    def _verify(e, ctx: dict[str, Any]) -> tuple[bool, str]:
        del e
        target = ctx.get("win")
        if target is None:
            return False, "window_missing"
        time.sleep(0.1)
        return _window_is_minimized(target), "minimized"

    return run_action(
        "minimize_window",
        _act,
        _verify,
        [engine],
        max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
        context=context,
    )


def minimize_orchestrated(
    config_or_win: dict[str, Any] | Any,
    session: UiAutomationSession | None = None,
    *,
    settle_ms: int = 150,
    config: dict[str, Any] | None = None,
    engine: str = "pywinauto",
) -> dict[str, Any]:
    """Minimize through orchestrator.

    Supports both signatures:
    - minimize_orchestrated(config, session) for send cleanup
    - minimize_orchestrated(win, settle_ms=..., config=...) for direct callers
    """
    del engine
    if session is not None or isinstance(config_or_win, dict):
        cfg = config_or_win if isinstance(config_or_win, dict) else (config or {})
        sess = session if session is not None else UiAutomationSession()
        return _minimize_with_session(cfg, sess)
    return _minimize_direct(
        config_or_win,
        settle_ms=settle_ms,
        config=config,
    )

