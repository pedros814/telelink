from __future__ import annotations

import ctypes
from importlib import import_module
from typing import Any
from urllib.parse import urlparse

DEFAULT_SERVER_URL = "http://127.0.0.1:4723"
DEFAULT_PHONE_LINK_APP = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
_TITLE_KEYS = ("phone link", "your phone", "messages", "messaging")

_DEFAULT_LOCATORS: dict[str, tuple[str, ...]] = {
    "send_accessibility_ids": ("Send", "SendButton", "send"),
    "send_names": ("Send", "Send message"),
    "minimize_accessibility_ids": ("Minimize", "MinimizeButton"),
    "minimize_names": ("Minimize",),
    "titlebar_names": ("Title Bar",),
}


try:
    from telelink.ui_automation.engines.base import UiEngine as _UiEngineBase
except Exception:
    class _UiEngineBase:
        """Fallback base when ui_automation.engines.base is not present yet."""


class AppiumEngine(_UiEngineBase):
    name = "appium"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._session = None
        self._last_hwnd: int | None = None
        self._last_error = ""

    @staticmethod
    def available() -> bool:
        try:
            import_module("appium.webdriver")
            return True
        except Exception:
            return False

    def _appium_config(self) -> dict[str, Any]:
        automation = (self.config.get("automation") if isinstance(self.config, dict) else {}) or {}
        return (automation.get("appium") if isinstance(automation, dict) else {}) or {}

    def _server_url(self) -> str:
        appium_cfg = self._appium_config()
        url = str(appium_cfg.get("server_url") or DEFAULT_SERVER_URL).rstrip("/")
        use_server = appium_cfg.get("use_appium_server", False)
        if isinstance(use_server, str):
            use_server = use_server.strip().lower() in {"1", "true", "yes", "on"}
        if bool(use_server):
            parsed = urlparse(url)
            if parsed.path in ("", "/") and not url.lower().endswith("/wd/hub"):
                return f"{url}/wd/hub"
        return url

    def _session_timeout_seconds(self) -> int:
        appium_cfg = self._appium_config()
        try:
            return int(appium_cfg.get("session_timeout_seconds", 30))
        except (TypeError, ValueError):
            return 30

    def _phone_link_app_id(self) -> str:
        appium_cfg = self._appium_config()
        app_id = str(appium_cfg.get("phone_link_app") or "").strip()
        return app_id or DEFAULT_PHONE_LINK_APP

    def _attach_to_existing(self) -> bool:
        appium_cfg = self._appium_config()
        value = appium_cfg.get("attach_to_existing", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _load_appium(self):
        try:
            from appium import webdriver
            from appium.options.common import AppiumOptions
            from appium.webdriver.common.appiumby import AppiumBy

            return webdriver, AppiumOptions, AppiumBy
        except Exception:
            return None

    def _find_phone_link_hwnd(self) -> int | None:
        try:
            from telelink.ui_automation.session import find_phone_link_window

            win = find_phone_link_window(timeout_s=0.5)
            if win is not None:
                hwnd = int(getattr(win, "handle", 0) or 0)
                if hwnd > 0:
                    return hwnd
        except Exception:
            pass
        return None

    def _new_session(self, capabilities: dict[str, Any]):
        loaded = self._load_appium()
        if loaded is None:
            return None
        webdriver, AppiumOptions, _ = loaded

        try:
            options = AppiumOptions()
            options.load_capabilities(capabilities)
            return webdriver.Remote(command_executor=self._server_url(), options=options)
        except Exception as exc:
            self._last_error = str(exc)
            return None

    def _base_capabilities(self) -> dict[str, Any]:
        return {
            "platformName": "Windows",
            "deviceName": "WindowsPC",
            "appium:newCommandTimeout": self._session_timeout_seconds(),
        }

    def _ensure_session(self, win_or_session: Any = None):
        if win_or_session is not None and hasattr(win_or_session, "find_elements"):
            return win_or_session
        if self._session is not None:
            return self._session
        return self.find_phone_link_window()

    def _load_locator_values(self) -> dict[str, tuple[str, ...]]:
        values = dict(_DEFAULT_LOCATORS)
        try:
            locators = import_module("telelink.ui_automation.locators")
        except Exception:
            return values

        alias_map = {
            "send_accessibility_ids": (
                "SEND_BUTTON_ACCESSIBILITY_IDS",
                "SEND_ACCESSIBILITY_IDS",
                "PHONE_LINK_SEND_ACCESSIBILITY_IDS",
            ),
            "send_names": ("SEND_BUTTON_NAMES", "SEND_NAMES", "PHONE_LINK_SEND_NAMES"),
            "minimize_accessibility_ids": (
                "MINIMIZE_BUTTON_ACCESSIBILITY_IDS",
                "MINIMIZE_ACCESSIBILITY_IDS",
                "PHONE_LINK_MINIMIZE_ACCESSIBILITY_IDS",
            ),
            "minimize_names": (
                "MINIMIZE_BUTTON_NAMES",
                "MINIMIZE_NAMES",
                "PHONE_LINK_MINIMIZE_NAMES",
            ),
            "titlebar_names": ("TITLE_BAR_NAMES", "PHONE_LINK_TITLE_BAR_NAMES"),
        }

        for target_key, aliases in alias_map.items():
            for attr in aliases:
                value = getattr(locators, attr, None)
                if isinstance(value, str) and value.strip():
                    values[target_key] = (value.strip(),)
                    break
                if isinstance(value, (list, tuple)):
                    cleaned = tuple(str(v).strip() for v in value if str(v).strip())
                    if cleaned:
                        values[target_key] = cleaned
                        break
        return values

    def _click_first(self, elements: list[Any]) -> bool:
        for element in elements:
            try:
                element.click()
                return True
            except Exception:
                continue
        return False

    def _find_by_accessibility_ids(self, session, appium_by, candidates: tuple[str, ...]) -> list[Any]:
        results: list[Any] = []
        for value in candidates:
            if not value:
                continue
            try:
                exact = session.find_elements(appium_by.ACCESSIBILITY_ID, value)
                if exact:
                    results.extend(exact)
                    continue
            except Exception:
                pass
            escaped = value.lower().replace("'", "")
            xpath = (
                "//*[contains(translate(@AutomationId,"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
                f" '{escaped}')]"
            )
            try:
                results.extend(session.find_elements(appium_by.XPATH, xpath))
            except Exception:
                continue
        return results

    def _find_by_names(self, session, appium_by, candidates: tuple[str, ...]) -> list[Any]:
        results: list[Any] = []
        for value in candidates:
            if not value:
                continue
            try:
                exact = session.find_elements(appium_by.NAME, value)
                if exact:
                    results.extend(exact)
                    continue
            except Exception:
                pass
            escaped = value.lower().replace("'", "")
            xpath = (
                "//*[contains(translate(@Name,"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
                f" '{escaped}')]"
            )
            try:
                results.extend(session.find_elements(appium_by.XPATH, xpath))
            except Exception:
                continue
        return results

    def find_phone_link_window(self):
        """Attach to Phone Link via appTopLevelWindow (preferred) or app AUMID."""
        if not self.available():
            return False

        capabilities = self._base_capabilities()
        if self._attach_to_existing():
            hwnd = self._find_phone_link_hwnd()
            if hwnd:
                self._last_hwnd = hwnd
                session = self._new_session(
                    {**capabilities, "appTopLevelWindow": hex(hwnd)}
                )
                if session is not None:
                    self._session = session
                    return session

        session = self._new_session({**capabilities, "app": self._phone_link_app_id()})
        if session is None:
            return False
        self._session = session
        return session

    def click_send(self, win_or_session: Any, body: str) -> bool:
        _ = body  # reserved for verify-aware engine interfaces
        session = self._ensure_session(win_or_session)
        if not session:
            return False
        loaded = self._load_appium()
        if loaded is None:
            return False
        _, _, appium_by = loaded
        locators = self._load_locator_values()

        send_elements = self._find_by_accessibility_ids(
            session, appium_by, locators["send_accessibility_ids"]
        )
        if self._click_first(send_elements):
            return True

        send_elements = self._find_by_names(session, appium_by, locators["send_names"])
        if self._click_first(send_elements):
            return True

        try:
            generic = session.find_elements(
                appium_by.XPATH,
                "//*[@LocalizedControlType='button' and "
                "contains(translate(@Name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send')]",
            )
            return self._click_first(generic)
        except Exception:
            return False

    def unfocus_compose(self, win_or_session: Any) -> bool:
        session = self._ensure_session(win_or_session)
        if not session:
            return False
        loaded = self._load_appium()
        if loaded is None:
            return False
        _, _, appium_by = loaded
        locators = self._load_locator_values()

        try:
            title_elements = self._find_by_names(
                session, appium_by, locators["titlebar_names"]
            )
            if self._click_first(title_elements):
                return True
        except Exception:
            pass

        try:
            bars = session.find_elements(
                appium_by.XPATH, "//*[@LocalizedControlType='title bar']"
            )
            if self._click_first(bars):
                return True
        except Exception:
            pass

        try:
            root = session.find_element(appium_by.XPATH, "/*")
            root.click()
            return True
        except Exception:
            return False

    def _show_window_minimize(self, hwnd: int | None) -> bool:
        if not hwnd:
            return False
        try:
            return bool(ctypes.windll.user32.ShowWindow(int(hwnd), 6))  # SW_MINIMIZE
        except Exception:
            return False

    def minimize_window(self, win_or_session: Any) -> bool:
        session = self._ensure_session(win_or_session)
        if not session:
            return False
        loaded = self._load_appium()
        if loaded is None:
            return False
        _, _, appium_by = loaded
        locators = self._load_locator_values()

        buttons = self._find_by_accessibility_ids(
            session, appium_by, locators["minimize_accessibility_ids"]
        )
        if self._click_first(buttons):
            return True

        buttons = self._find_by_names(session, appium_by, locators["minimize_names"])
        if self._click_first(buttons):
            return True

        try:
            generic = session.find_elements(
                appium_by.XPATH,
                "//*[@LocalizedControlType='button' and "
                "contains(translate(@Name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'minimize')]",
            )
            if self._click_first(generic):
                return True
        except Exception:
            pass

        hwnd = self._last_hwnd
        if not hwnd:
            try:
                raw = (session.capabilities or {}).get("appTopLevelWindow")
                if isinstance(raw, str):
                    hwnd = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 16)
                elif isinstance(raw, int):
                    hwnd = raw
            except Exception:
                hwnd = None
        return self._show_window_minimize(hwnd)
