"""Window/session helpers for Phone Link UI automation."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from telelink.contacts import dial_digits

# Phone Link UWP host (Link to Windows / Your Phone).
_PHONE_LINK_PROCESS_NAMES = frozenset({"phoneexperiencehost.exe"})

# Never treat editor/IDE windows as Phone Link even if the title mentions it.
_EDITOR_PROCESS_NAMES = frozenset(
    {
        "sublime_text.exe",
        "code.exe",
        "cursor.exe",
        "devenv.exe",
        "notepad.exe",
        "notepad++.exe",
        "pycharm64.exe",
        "idea64.exe",
    }
)

_DEFAULT_AUMID = "Microsoft.YourPhone_8wekyb3d8bbwe!App"


@dataclass
class UiAutomationSession:
    """Engine-agnostic automation session; stores optional pywinauto handle."""

    pywinauto_window: Any | None = None


def _process_image_name(pid: int) -> str:
    if sys.platform != "win32" or pid <= 0:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_uint32(260)
        try:
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def phone_link_title_match(title: str, *, process_name: str = "") -> bool:
    """
    True for the real Phone Link top-level window.

    Substring checks alone are unsafe — e.g. a Sublime tab titled
    "TeleLink Phone Link DB …" must not match.
    """
    proc = (process_name or "").lower()
    if proc in _PHONE_LINK_PROCESS_NAMES:
        return True
    if proc in _EDITOR_PROCESS_NAMES:
        return False

    t = (title or "").strip().lower()
    if not t:
        return False

    if t in ("phone link", "your phone", "link to windows"):
        return True
    # Short titles only — reject long editor/browser tab titles.
    if len(t) <= 48 and t.startswith("phone link"):
        return True
    if len(t) <= 48 and t.startswith("your phone"):
        return True
    return False


def _window_process_name(win: Any) -> str:
    try:
        return _process_image_name(int(win.process_id()))
    except Exception:
        return ""


def _phone_link_aumid(config: dict[str, Any] | None) -> str:
    pl = (config or {}).get("phone_link") or {}
    for raw in pl.get("app_user_model_ids") or []:
        value = str(raw or "").strip()
        if value and "yourphone" in value.lower():
            return value
    return _DEFAULT_AUMID


def launch_phone_link(*, config: dict[str, Any] | None = None, wait_s: float = 3.0) -> bool:
    """Start Phone Link if it is not already open."""
    if sys.platform != "win32":
        return False
    if find_phone_link_window(config=config, timeout_s=0.5):
        return True

    aumid = _phone_link_aumid(config)
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    for cmd in (
        ["explorer.exe", f"shell:AppsFolder\\{aumid}"],
        ["cmd", "/c", "start", "", f"shell:AppsFolder\\{aumid}"],
    ):
        try:
            subprocess.run(cmd, check=False, creationflags=flags)
            break
        except OSError:
            continue
    else:
        return False

    deadline = time.monotonic() + max(0.5, wait_s)
    while time.monotonic() < deadline:
        if find_phone_link_window(config=config, timeout_s=0.5):
            return True
        time.sleep(0.35)
    return find_phone_link_window(config=config, timeout_s=0.0) is not None


def open_sms_thread_uri(phone: str) -> bool:
    """Open Phone Link Messages for a number (best-effort thread navigation)."""
    if sys.platform != "win32":
        return False
    dial = dial_digits(phone)
    if len(dial) < 7:
        return False
    uri = f"sms:{dial}"
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        subprocess.run(["cmd", "/c", "start", "", uri], check=False, creationflags=flags)
        return True
    except OSError:
        return False


def find_phone_link_window(
    *,
    session: UiAutomationSession | None = None,
    config: dict[str, Any] | None = None,
    timeout_s: float = 0.0,
    backend: str = "uia",
) -> Any | None:
    """Best-effort Phone Link top-level window lookup via pywinauto."""
    if sys.platform != "win32":
        return None

    cached = session.pywinauto_window if session else None
    if cached is not None:
        try:
            title = cached.window_text() or ""
            if phone_link_title_match(title, process_name=_window_process_name(cached)):
                return cached
        except Exception:
            pass

    try:
        from pywinauto import Desktop
    except ImportError:
        return None

    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        best = None
        try:
            desktop = Desktop(backend=backend or "uia")
            for win in desktop.windows():
                try:
                    title = win.window_text() or ""
                    proc = _window_process_name(win)
                    if not phone_link_title_match(title, process_name=proc):
                        continue
                    # Prefer the canonical Phone Link process over title-only matches.
                    if proc in _PHONE_LINK_PROCESS_NAMES:
                        if session is not None:
                            session.pywinauto_window = win
                        return win
                    if best is None:
                        best = win
                except Exception:
                    continue
        except Exception:
            pass

        if best is not None:
            if session is not None:
                session.pywinauto_window = best
            return best

        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    if session is not None:
        session.pywinauto_window = None
    return None
