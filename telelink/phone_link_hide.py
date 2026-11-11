"""Keep Phone Link invisible while TeleLink drives it (no open/close flash).

Why not minimise: a minimised window is restored on screen every time Phone Link is activated
(``sms:`` / ``tel:`` link), then minimised again — the user sees it open and close. A window that is
NOT minimised but placed off-screen stays invisible when activated, and UI Automation still works on
it (buttons are pressed with UIA Invoke, no mouse).

The user keeps control: clicking Phone Link in the taskbar activates it → the watcher brings it back
on screen (where it was). When the user switches away, it goes back off-screen. Nothing is hidden
while an automation holds ``UI_LOCK``.

Config: ``automation.phone_link_window``: ``offscreen`` (default) | ``minimize`` (old behaviour).
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

OFFSCREEN_X = -32000
OFFSCREEN_Y = -32000
PHONE_LINK_PROCESSES = ("phoneexperiencehost.exe", "yourphone.exe")

# hwnd -> (left, top, right, bottom) on-screen rect remembered before hiding
_saved_rects: dict[int, tuple[int, int, int, int]] = {}

# Après un envoi, Windows laisse souvent Phone Link au premier plan : ce n'est pas l'utilisateur qui l'a
# ouvert. Pendant ce délai (et pendant tout un appel), on ne le remet jamais à l'écran.
QUIET_AFTER_AUTOMATION_S = 8.0
_quiet_until = 0.0
_call_active = False


def set_call_active(active: bool) -> None:
    """Appel en cours par le pont : Phone Link reste hors écran même s'il passe au premier plan."""
    global _call_active, _quiet_until
    _call_active = bool(active)
    if not active:
        _quiet_until = max(_quiet_until, time.monotonic() + QUIET_AFTER_AUTOMATION_S)


def user_may_show(now: float | None = None) -> bool:
    """L'utilisateur peut-il être à l'origine du premier plan ? (ni appel en cours, ni envoi récent)"""
    t = time.monotonic() if now is None else now
    return not _call_active and t >= _quiet_until


def window_mode(config: dict[str, Any] | None) -> str:
    mode = str(((config or {}).get("automation") or {}).get("phone_link_window") or "offscreen").lower()
    return mode if mode in ("offscreen", "minimize", "normal") else "offscreen"


def is_offscreen(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right <= -1000 or bottom <= -1000 or left <= OFFSCREEN_X + 1000


def decide(hwnd: int, *, rect: tuple[int, int, int, int], foreground: bool, automation_running: bool) -> str:
    """'show' | 'hide' | 'keep' for one Phone Link window (pure logic, tested)."""
    if automation_running:
        return "keep"
    hidden = is_offscreen(rect)
    if foreground:
        return "show" if hidden else "keep"
    return "keep" if hidden else "hide"


# ---------------------------------------------------------------- Win32 (ctypes)


def _user32():
    import ctypes

    return ctypes.windll.user32


def _rect(hwnd: int) -> tuple[int, int, int, int] | None:
    import ctypes
    from ctypes import wintypes

    r = wintypes.RECT()
    if not _user32().GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def phone_link_hwnds() -> list[int]:
    """Visible top-level windows owned by Phone Link."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    from telelink.ui_automation.session import _process_image_name

    user32 = _user32()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER: skip owned popups
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _process_image_name(int(pid.value)).lower() in PHONE_LINK_PROCESSES:
                found.append(int(hwnd))
        except Exception:  # noqa: BLE001
            pass
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _set_normal_position(hwnd: int, left: int, top: int, width: int, height: int, show_cmd: int) -> bool:
    """SetWindowPlacement: works for minimised and normal windows, without activating them."""
    import ctypes
    from ctypes import wintypes

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.UINT),
            ("flags", wintypes.UINT),
            ("showCmd", wintypes.UINT),
            ("ptMinPosition", wintypes.POINT),
            ("ptMaxPosition", wintypes.POINT),
            ("rcNormalPosition", wintypes.RECT),
        ]

    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not _user32().GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return False
    wp.showCmd = show_cmd
    wp.rcNormalPosition = wintypes.RECT(left, top, left + width, top + height)
    return bool(_user32().SetWindowPlacement(hwnd, ctypes.byref(wp)))


def hide_hwnd(hwnd: int) -> bool:
    """Move off-screen, not minimised, without activating it."""
    user32 = _user32()
    rect = _rect(hwnd)
    if rect is None:
        return False
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        # Remember the restored size, then place the normal position off-screen and show it there.
        width, height = 1000, 750
        ok = _set_normal_position(hwnd, OFFSCREEN_X, OFFSCREEN_Y, width, height, 4)  # SW_SHOWNOACTIVATE
        return ok
    if not is_offscreen(rect):
        _saved_rects[hwnd] = rect
    left, top, right, bottom = rect
    SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
    return bool(user32.SetWindowPos(hwnd, 0, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))


def show_hwnd(hwnd: int) -> bool:
    """Bring a hidden window back where it was (or centred on the main screen)."""
    user32 = _user32()
    rect = _rect(hwnd) or (0, 0, 1000, 750)
    width, height = max(400, rect[2] - rect[0]), max(300, rect[3] - rect[1])
    saved = _saved_rects.get(hwnd)
    if saved:
        left, top = saved[0], saved[1]
    else:
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        left, top = max(0, (sw - width) // 2), max(0, (sh - height) // 2)
    SWP_NOSIZE, SWP_NOZORDER = 0x0001, 0x0004
    return bool(user32.SetWindowPos(hwnd, 0, left, top, 0, 0, SWP_NOSIZE | SWP_NOZORDER))


def hide_all(config: dict[str, Any] | None = None) -> int:
    if sys.platform != "win32" or window_mode(config) != "offscreen":
        return 0
    n = 0
    for hwnd in phone_link_hwnds():
        try:
            if hide_hwnd(hwnd):
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def show_all() -> int:
    if sys.platform != "win32":
        return 0
    n = 0
    for hwnd in phone_link_hwnds():
        try:
            rect = _rect(hwnd)
            if rect and is_offscreen(rect) and show_hwnd(hwnd):
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def watch_once(lock: Any) -> None:
    """One pass: hide Phone Link unless the user is looking at it; never during an automation."""
    if sys.platform != "win32":
        return
    global _quiet_until
    acquired = lock.acquire(blocking=False)
    if not acquired:
        # Envoi ou appel en cours : on ne touche à rien, et on ignore le premier plan juste après.
        _quiet_until = time.monotonic() + QUIET_AFTER_AUTOMATION_S
        return
    try:
        foreground = int(_user32().GetForegroundWindow() or 0)
        allow_show = user_may_show()
        for hwnd in phone_link_hwnds():
            rect = _rect(hwnd)
            if rect is None:
                continue
            action = decide(hwnd, rect=rect, foreground=allow_show and hwnd == foreground, automation_running=False)
            if action == "hide":
                hide_hwnd(hwnd)
            elif action == "show":
                show_hwnd(hwnd)
    finally:
        if acquired:
            lock.release()


def start_watcher(get_config: Any, *, interval_s: float = 0.4) -> threading.Event:
    """Background thread keeping Phone Link invisible (mode ``offscreen``)."""
    from telelink.phone_link_dial import UI_LOCK

    stop = threading.Event()

    def _run() -> None:
        while not stop.is_set():
            try:
                if window_mode(get_config()) == "offscreen":
                    watch_once(UI_LOCK)
            except Exception:  # noqa: BLE001 — never kill the bridge for a cosmetic feature
                pass
            stop.wait(interval_s)
        try:
            show_all()  # bridge stopping: give the window back
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, name="zns-phone-link-hide", daemon=True).start()
    return stop
