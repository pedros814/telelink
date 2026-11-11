"""Send action wiring for orchestrated UI automation."""

from __future__ import annotations

import time
from typing import Any

from telelink.ui_automation.config_helpers import get_automation_config
from telelink.ui_automation.engines.appium_engine import AppiumEngine
from telelink.ui_automation.engines.keys_engine import KeysEngine
from telelink.ui_automation.engines.pywinauto_engine import PywinautoEngine
from telelink.ui_automation.orchestrator import run_action
from telelink.ui_automation.session import UiAutomationSession, find_phone_link_window
from telelink.ui_automation.verify.predicates import verify_send_delivered


def _build_engine_chain(config: dict[str, Any]) -> tuple[list[Any], bool]:
    auto_cfg = get_automation_config(config)
    messaging = config.get("messaging") or {}

    engines: list[Any] = []
    has_keys_in_chain = False
    for name in auto_cfg.get("engine_chain", []):
        engine = str(name or "").strip().lower()
        if engine == "pywinauto":
            engines.append(PywinautoEngine(config))
        elif engine == "appium" and AppiumEngine.available():
            engines.append(AppiumEngine(config))
        elif engine == "keys":
            has_keys_in_chain = True
            engines.append(KeysEngine(delay_ms=int(messaging.get("auto_delay_ms", 2200))))

    if not engines:
        engines.append(PywinautoEngine(config))
    return engines, has_keys_in_chain


def _verify_window_handle(win: Any, session: UiAutomationSession) -> Any:
    """Use pywinauto window for verify when act used an Appium session."""
    if win is not None and hasattr(win, "descendants"):
        return win
    return find_phone_link_window(session=session)


def click_send_with_orchestrator(
    body: str,
    config: dict[str, Any],
    session: UiAutomationSession,
    *,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Run click-send through orchestrator and return send-focused fields."""
    auto_cfg = get_automation_config(config)
    messaging = config.get("messaging") or {}
    verify_before_unfocus = bool(messaging.get("auto_verify_before_unfocus", True))

    engines, has_keys_in_chain = _build_engine_chain(config)
    keys_engine = KeysEngine(delay_ms=int(messaging.get("auto_delay_ms", 2200)))

    started = time.monotonic()
    context: dict[str, Any] = {"win": session.pywinauto_window}

    def _act(engine, ctx: dict[str, Any]) -> bool:
        win = ctx.get("win")
        if win is None:
            remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
            win = engine.find_phone_link_window(session=session)
            if win is None and remaining > 0:
                win = engine.find_phone_link_window(session=session)
            if win is None:
                return False
            ctx["win"] = win
        # UN SEUL clic sur Envoyer, quoi qu'il arrive : un SMS parti ne doit jamais repartir.
        # Les tentatives suivantes ne recliquent pas, elles laissent seulement plus de temps à la vérification.
        if ctx.get("clicked"):
            return True
        if "compose_seen" not in ctx:
            from telelink.ui_automation.verify.predicates import compose_shows_body, count_sent_bubbles

            ctx["compose_seen"] = compose_shows_body(win, body)
            ctx["bubbles_before"] = count_sent_bubbles(win, body)
        clicked = bool(engine.click_send(win, body))
        if clicked:
            ctx["clicked"] = True
        return clicked

    def _verify(engine, ctx: dict[str, Any]) -> tuple[bool, str]:
        del engine
        if not verify_before_unfocus:
            return True, "verify_disabled"
        win = _verify_window_handle(ctx.get("win"), session)
        if win is None:
            return False, "window_missing"
        return verify_send_delivered(
            win,
            body,
            timeout_ms=int(auto_cfg.get("verify_timeout_ms", 8000)),
            poll_ms=int(auto_cfg.get("verify_poll_ms", 400)),
            compose_seen=bool(ctx.get("compose_seen")),
            bubbles_before=ctx.get("bubbles_before"),
        )

    def _last_resort(ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("clicked"):
            # Envoyer a déjà été cliqué : appuyer sur Entrée risquerait un second SMS.
            return False, "already_clicked"
        if not auto_cfg.get("fallback", {}).get("send_keys_enter", True):
            return False, "fallback_disabled"
        win = ctx.get("win")
        sent = keys_engine.click_send(win, body)
        if sent:
            ctx["clicked"] = True
        return sent, "fallback_keys"

    result = run_action(
        "click_send",
        _act,
        _verify,
        engines,
        max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
        last_resort_fn=None if has_keys_in_chain else _last_resort,
        context=context,
    )

    attempts = result.get("attempts") or []
    send_clicked = any(bool(a.get("acted")) for a in attempts)
    verify_method = str(result.get("verify_method") or "")
    send_verified = bool(result.get("ok")) and verify_method not in (
        "fallback_keys",
        "fallback_disabled",
    )

    return {
        **result,
        "send_clicked": send_clicked,
        "send_verified": send_verified,
    }
