"""Config helpers for automation migration (automation + legacy messaging keys)."""

from __future__ import annotations

from typing import Any


def _as_engine_chain(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        values = [p.strip().lower() for p in raw_value.split(",")]
        return [v for v in values if v]
    if isinstance(raw_value, list):
        out: list[str] = []
        for item in raw_value:
            value = str(item or "").strip().lower()
            if value:
                out.append(value)
        return out
    return []


def get_automation_config(config: dict[str, Any]) -> dict[str, Any]:
    """
    Merge config.automation with legacy messaging.auto_* keys.

    Defaults:
      engine_chain=[pywinauto]
      max_attempts_per_engine=2
      verify_timeout_ms=8000
      verify_poll_ms=400
    """
    cfg = config or {}
    messaging = cfg.get("messaging") or {}
    automation_raw = cfg.get("automation") or {}

    chain = _as_engine_chain(automation_raw.get("engine_chain"))
    if not chain:
        legacy_engine = str(messaging.get("auto_engine", "pywinauto") or "pywinauto").lower()
        chain = [legacy_engine]
    if not chain:
        chain = ["pywinauto"]

    max_attempts = int(
        automation_raw.get(
            "max_attempts_per_engine",
            messaging.get("auto_send_attempts", 2),
        )
    )
    verify_timeout_ms = int(
        automation_raw.get(
            "verify_timeout_ms",
            messaging.get("auto_verify_timeout_ms", 8000),
        )
    )
    verify_poll_ms = int(
        automation_raw.get(
            "verify_poll_ms",
            messaging.get("auto_verify_poll_ms", 400),
        )
    )

    pywinauto_cfg = dict(automation_raw.get("pywinauto") or {})
    pywinauto_cfg.setdefault("backend", "uia")

    fallback_cfg = dict(automation_raw.get("fallback") or {})
    fallback_cfg.setdefault("send_keys_enter", True)
    fallback_cfg.setdefault("minimize_showwindow", True)

    return {
        "enabled": bool(automation_raw.get("enabled", True)),
        "engine_chain": chain,
        "max_attempts_per_engine": max(1, max_attempts),
        "verify_timeout_ms": max(200, verify_timeout_ms),
        "verify_poll_ms": max(100, verify_poll_ms),
        "pywinauto": pywinauto_cfg,
        "appium": dict(automation_raw.get("appium") or {}),
        "fallback": fallback_cfg,
    }
