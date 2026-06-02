"""Windows console/window focus — background watcher + return to TeleLink shell."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable


def get_console_hwnd() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        return int(hwnd) if hwnd else None
    except Exception:
        return None


def _user32():
    import ctypes

    return ctypes.windll.user32


def focus_window(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes

        user32 = _user32()
        kernel32 = ctypes.windll.kernel32
        if user32.GetForegroundWindow() == hwnd:
            return True
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(current_thread, fg_thread, True)
        user32.AttachThreadInput(current_thread, target_thread, True)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.AttachThreadInput(current_thread, fg_thread, False)
        user32.AttachThreadInput(current_thread, target_thread, False)
        return True
    except Exception:
        return False


def minimize_window(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        return bool(_user32().ShowWindow(hwnd, 6))  # SW_MINIMIZE
    except Exception:
        return False


def find_window_by_title(
    title_substring: str,
    *,
    predicate: Callable[[str], bool] | None = None,
) -> int | None:
    if sys.platform != "win32" or not title_substring:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        found: list[int] = []
        needle = title_substring.lower()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""
            if predicate is not None:
                if predicate(title):
                    found.append(int(hwnd))
            elif needle in title.lower():
                found.append(int(hwnd))
            return True

        user32.EnumWindows(_enum, 0)
        return found[0] if found else None
    except Exception:
        return None


def wait_for_window_title(title_substring: str, *, timeout: float = 5.0) -> int | None:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        hwnd = find_window_by_title(title_substring)
        if hwnd:
            return hwnd
        time.sleep(0.15)
    return None


def minimize_uia_window(
    win: Any,
    *,
    settle_ms: int = 150,
    config: dict[str, Any] | None = None,
) -> bool:
    """Minimize a pywinauto window (Phone Link, etc.)."""
    if win is None:
        return False
    try:
        from telelink.ui_automation.actions import window as window_actions

        minimize_orchestrated = getattr(window_actions, "minimize_orchestrated", None)
        if callable(minimize_orchestrated):
            result = minimize_orchestrated(
                win,
                settle_ms=settle_ms,
                config=config,
                engine="pywinauto",
            )
            if isinstance(result, dict):
                return bool(result.get("ok"))
            return bool(result)
    except Exception:
        pass
    if settle_ms > 0:
        time.sleep(settle_ms / 1000.0)
    for spec in (
        {"title_re": r"(?i)^minimize$", "control_type": "Button"},
        {"title": "Minimize", "control_type": "Button"},
        {"auto_id_re": r"(?i).*minimize.*", "control_type": "Button"},
    ):
        try:
            btn = win.child_window(**spec)
            if btn.exists(timeout=0.3):
                btn.click_input()
                return True
        except Exception:
            continue
    try:
        win.minimize()
        return True
    except Exception:
        pass
    try:
        hwnd = int(win.handle)
        return minimize_window(hwnd)
    except Exception:
        return False


def refocus_telelink_shell(*, shell_hwnd: int | None = None) -> bool:
    hwnd = shell_hwnd or get_console_hwnd()
    if not hwnd:
        return False
    return focus_window(hwnd)


def handoff_to_shell(
    *,
    external_title: str | None = None,
    external_hwnd: int | None = None,
    uia_window: Any | None = None,
    shell_hwnd: int | None = None,
    settle_ms: int = 200,
) -> None:
    """Minimize a secondary window and return focus to the TeleLink shell console."""
    if sys.platform != "win32":
        return
    if uia_window is not None:
        minimize_uia_window(uia_window, settle_ms=settle_ms)
    elif external_hwnd:
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        minimize_window(external_hwnd)
    elif external_title:
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        hwnd = find_window_by_title(external_title)
        if hwnd:
            minimize_window(hwnd)
    refocus_telelink_shell(shell_hwnd=shell_hwnd)


def background_watcher_handoff(*, shell_hwnd: int | None = None, settle_ms: int = 400) -> None:
    """After spawning TeleLink Watcher — minimize it and refocus the shell."""
    hwnd = wait_for_window_title("TeleLink Watcher", timeout=5.0)
    handoff_to_shell(
        external_hwnd=hwnd,
        shell_hwnd=shell_hwnd,
        settle_ms=settle_ms,
    )
