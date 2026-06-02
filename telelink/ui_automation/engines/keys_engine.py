"""Keyboard-based fallback automation engine."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any

from telelink.ui_automation.session import UiAutomationSession, find_phone_link_window


class KeysEngine:
    name = "keys"

    def __init__(self, delay_ms: int = 2200):
        self.delay_ms = int(delay_ms)

    def available(self) -> bool:
        return sys.platform == "win32"

    def find_phone_link_window(self, session: UiAutomationSession | None = None):
        return find_phone_link_window(session=session, timeout_s=0.0, backend="uia")

    def click_send(self, win: Any, body: str) -> bool:
        del win, body
        return send_keys_enter(self.delay_ms)

    def unfocus_compose(self, win: Any) -> bool:
        del win
        return False

    def minimize_window(self, win: Any) -> bool:
        del win
        return False


def send_keys_enter(delay_ms: int = 2200) -> bool:
    """Fallback: assume compose window has focus; press Enter."""
    if sys.platform != "win32":
        return False
    time.sleep(max(0, int(delay_ms)) / 1000.0)
    ps = r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        return True
    except OSError:
        return False
