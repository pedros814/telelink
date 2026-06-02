"""TeleLink UI automation orchestration package."""

from __future__ import annotations

from typing import Any

from telelink.ui_automation.config_helpers import get_automation_config
from telelink.ui_automation.engines.appium_engine import AppiumEngine
from telelink.ui_automation.engines.base import UiEngine
from telelink.ui_automation.orchestrator import run_action
from telelink.ui_automation.session import UiAutomationSession


def _enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return True
    return bool(value)


def get_engine_chain(config: dict[str, Any] | None = None) -> list[str]:
    """Return orchestrator engine order from config (filters unavailable engines)."""
    cfg = config if isinstance(config, dict) else {}
    chain = list(get_automation_config(cfg).get("engine_chain") or ["pywinauto"])
    if not _enabled((cfg.get("automation") or {}).get("enabled", True)):
        return ["pywinauto"]
    out: list[str] = []
    for name in chain:
        engine = str(name or "").strip().lower()
        if engine == "appium" and not AppiumEngine.available():
            continue
        if engine and engine not in out:
            out.append(engine)
    return out or ["pywinauto"]


__all__ = [
    "run_action",
    "get_automation_config",
    "UiEngine",
    "UiAutomationSession",
    "AppiumEngine",
    "get_engine_chain",
]

