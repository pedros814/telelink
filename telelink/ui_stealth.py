"""Keep Phone Link UI automation from stealing the user's desktop."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Generator

from telelink.ui_automation.config_helpers import get_automation_config


def stealth_ui_enabled(config: dict[str, Any] | None) -> bool:
    """True when automation should avoid popping Phone Link to the foreground."""
    cfg = config or {}
    auto = cfg.get("automation") or {}
    if auto.get("stealth_ui") is False:
        return False
    convo = cfg.get("convo") or {}
    if convo.get("stealth_ui") is False:
        return False
    return True


def ui_navigate_enabled(config: dict[str, Any] | None, *, for_ars: bool = False) -> bool:
    """Whether convo UI reads may launch Phone Link / open SMS URIs / switch threads."""
    cfg = config or {}
    if for_ars:
        ars = cfg.get("ars") or {}
        if "ui_navigate" in ars:
            return ars.get("ui_navigate") is not False
        return True
    convo = cfg.get("convo") or {}
    return convo.get("ui_navigate", True) is not False


def maybe_focus_window(
    win: Any,
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Focus Phone Link only when stealth is off or the action requires it."""
    if win is None:
        return False
    if stealth_ui_enabled(config) and not force:
        return False
    try:
        win.set_focus()
        return True
    except Exception:
        return False


def minimize_window_stealth(win: Any, config: dict[str, Any] | None = None) -> bool:
    """Minimize Phone Link without clicking chrome when stealth is enabled.

    Mode ``automation.phone_link_window: offscreen`` (défaut) : la fenêtre est placée hors de l'écran
    au lieu d'être réduite, pour qu'elle ne réapparaisse pas à chaque envoi.
    """
    if win is None:
        return False
    if sys.platform != "win32":
        return False

    from telelink.phone_link_hide import hide_hwnd, window_mode

    if window_mode(config) == "offscreen":
        try:
            if hide_hwnd(int(getattr(win, "handle"))):
                return True
        except Exception:
            pass

    auto = get_automation_config(config or {})
    fallback = auto.get("fallback") or {}
    use_showwindow = fallback.get("minimize_showwindow", True) is not False

    if use_showwindow:
        try:
            from telelink.win_console import minimize_window

            hwnd = int(getattr(win, "handle"))
            if minimize_window(hwnd):
                return True
        except Exception:
            pass

    try:
        win.minimize()
        return True
    except Exception:
        pass

    try:
        from telelink.win_console import minimize_window

        hwnd = int(getattr(win, "handle"))
        return minimize_window(hwnd)
    except Exception:
        return False


class StealthUiSession:
    """Remember the user's foreground window across a Phone Link automation block."""

    __slots__ = ("_config", "_previous_hwnd", "_phone_link_win")

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._previous_hwnd: int | None = None
        self._phone_link_win: Any | None = None

    def begin(self) -> None:
        if sys.platform != "win32" or not stealth_ui_enabled(self._config):
            return
        from telelink.win_console import get_foreground_hwnd

        self._previous_hwnd = get_foreground_hwnd()

    def track(self, win: Any | None) -> None:
        if win is not None:
            self._phone_link_win = win

    def finish(self) -> None:
        if sys.platform != "win32" or not stealth_ui_enabled(self._config):
            return
        win = self._phone_link_win
        if win is not None:
            minimize_window_stealth(win, self._config)
        if self._previous_hwnd:
            from telelink.win_console import restore_foreground

            restore_foreground(self._previous_hwnd)


@contextmanager
def stealth_ui(config: dict[str, Any] | None = None) -> Generator[StealthUiSession, None, None]:
    session = StealthUiSession(config)
    session.begin()
    try:
        yield session
    finally:
        session.finish()
