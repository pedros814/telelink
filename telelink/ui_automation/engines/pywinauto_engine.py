"""pywinauto implementation of UiEngine."""

from __future__ import annotations

import sys
import time
from typing import Any

from telelink.ui_automation.locators import (
    MINIMIZE_BUTTON_SPECS,
    SEND_BUTTON_SPECS,
    TITLE_BAR_SPECS,
)
from telelink.ui_automation.session import UiAutomationSession, find_phone_link_window


class PywinautoEngine:
    name = "pywinauto"

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._config = cfg
        self._automation = cfg.get("automation") or {}
        self._messaging = cfg.get("messaging") or {}
        self._pywinauto_cfg = self._automation.get("pywinauto") or {}

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import pywinauto  # noqa: F401
        except ImportError:
            return False
        return True

    def find_phone_link_window(self, session: UiAutomationSession | None = None):
        backend = str(self._pywinauto_cfg.get("backend", "uia") or "uia")
        return find_phone_link_window(session=session, backend=backend, timeout_s=0.0)

    def click_send(self, win, body: str) -> bool:
        del body
        from telelink.ui_stealth import maybe_focus_window

        maybe_focus_window(win, self._config, force=True)

        for spec in SEND_BUTTON_SPECS:
            try:
                btn = win.child_window(**spec)
                if btn.exists(timeout=0.3):
                    btn.click_input()
                    return True
            except Exception:
                continue

        try:
            from pywinauto.keyboard import send_keys
        except ImportError:
            return False

        try:
            send_keys("{ENTER}")
            return True
        except Exception:
            return False

    def unfocus_compose(self, win) -> bool:
        settle_ms = int(self._messaging.get("auto_unfocus_delay_ms", 250))
        ctrl_n_first = bool(self._messaging.get("auto_ctrl_n_before_unfocus", True))
        ctrl_n_gap_ms = int(self._messaging.get("auto_ctrl_n_gap_ms", 100))
        from telelink.ui_stealth import maybe_focus_window, stealth_ui_enabled

        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        maybe_focus_window(win, self._config, force=not stealth_ui_enabled(self._config))

        if ctrl_n_first:
            self._send_ctrl_n_to_window(win, config=self._config)
            if ctrl_n_gap_ms > 0:
                time.sleep(ctrl_n_gap_ms / 1000.0)

        for spec in TITLE_BAR_SPECS:
            try:
                bar = win.child_window(**spec)
                if bar.exists(timeout=0.3):
                    bar.click_input()
                    return True
            except Exception:
                continue

        try:
            rect = win.rectangle()
            width = rect.width()
            height = rect.height()
            if width < 8 or height < 8:
                return False
            x = width // 2
            y = min(16, max(8, height // 24))
            win.click_input(coords=(x, y))
            return True
        except Exception:
            return False

    def minimize_window(self, win) -> bool:
        from telelink.ui_stealth import minimize_window_stealth, maybe_focus_window, stealth_ui_enabled

        settle_ms = int(self._messaging.get("auto_minimize_delay_ms", 150))
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)

        if stealth_ui_enabled(self._config):
            if minimize_window_stealth(win, self._config):
                return True

        maybe_focus_window(win, self._config, force=True)

        for spec in MINIMIZE_BUTTON_SPECS:
            try:
                btn = win.child_window(**spec)
                if btn.exists(timeout=0.3):
                    btn.click_input()
                    return True
            except Exception:
                continue

        try:
            bar = win.child_window(control_type="TitleBar")
            if bar.exists(timeout=0.3):
                for spec in MINIMIZE_BUTTON_SPECS:
                    try:
                        btn = bar.child_window(**spec)
                        if btn.exists(timeout=0.3):
                            btn.click_input()
                            return True
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            win.minimize()
            return True
        except Exception:
            return False

    @staticmethod
    def _send_ctrl_n_to_window(win, *, config: dict[str, Any] | None = None) -> bool:
        try:
            from pywinauto.keyboard import send_keys
        except ImportError:
            return False
        try:
            from telelink.ui_stealth import maybe_focus_window

            maybe_focus_window(win, config, force=True)
            send_keys("^n")
            return True
        except Exception:
            return False
