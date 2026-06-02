"""Shared act/verify orchestrator for UI automation actions."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from telelink.ui_automation.engines.base import UiEngine

ActFn = Callable[[UiEngine, dict[str, Any]], bool]
VerifyFn = Callable[[UiEngine, dict[str, Any]], tuple[bool, str]]
LastResortFn = Callable[[dict[str, Any]], tuple[bool, str]]


def run_action(
    action_name: str,
    act_fn: ActFn,
    verify_fn: VerifyFn,
    engines: Iterable[UiEngine],
    *,
    max_attempts_per_engine: int = 2,
    last_resort_fn: LastResortFn | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run action across engines with verify-driven retries."""
    ctx = context if context is not None else {}
    engine_list = list(engines)
    attempts: list[dict[str, Any]] = []
    max_attempts = max(1, int(max_attempts_per_engine))
    verify_method = "not_run"
    last_engine = "none"

    for engine_idx, engine in enumerate(engine_list):
        engine_name = str(getattr(engine, "name", "unknown") or "unknown")
        last_engine = engine_name

        if not engine.available():
            verify_method = "engine_unavailable"
            attempts.append(
                {
                    "engine": engine_name,
                    "attempt": 0,
                    "acted": False,
                    "verified": False,
                    "verify_method": verify_method,
                }
            )
            continue

        for attempt_no in range(1, max_attempts + 1):
            acted = False
            verified = False
            method = "act_failed"
            error = ""

            try:
                acted = bool(act_fn(engine, ctx))
            except Exception as exc:
                acted = False
                method = "act_error"
                error = str(exc)

            if acted:
                try:
                    verified, method = verify_fn(engine, ctx)
                    method = method or ("verified" if verified else "verify_failed")
                except Exception as exc:
                    verified = False
                    method = "verify_error"
                    error = str(exc)

            verify_method = method
            row = {
                "engine": engine_name,
                "attempt": attempt_no,
                "acted": acted,
                "verified": verified,
                "verify_method": method,
            }
            if error:
                row["error"] = error
            attempts.append(row)

            if verified:
                fallback_used = engine_idx > 0
                note = f"{action_name} verified via {engine_name} ({method})"
                return {
                    "ok": True,
                    "action": action_name,
                    "engine": engine_name,
                    "attempts": attempts,
                    "verify_method": method,
                    "fallback_used": fallback_used,
                    "note": note,
                }

    if last_resort_fn is not None:
        ok = False
        method = "last_resort_failed"
        error = ""
        try:
            ok, method = last_resort_fn(ctx)
            method = method or ("last_resort_ok" if ok else "last_resort_failed")
        except Exception as exc:
            ok = False
            method = "last_resort_error"
            error = str(exc)

        verify_method = method
        row = {
            "engine": "last_resort",
            "attempt": 1,
            "acted": ok,
            "verified": ok,
            "verify_method": method,
        }
        if error:
            row["error"] = error
        attempts.append(row)
        note = f"{action_name} used last resort ({method})"
        return {
            "ok": ok,
            "action": action_name,
            "engine": "last_resort",
            "attempts": attempts,
            "verify_method": method,
            "fallback_used": True,
            "note": note,
        }

    note = f"{action_name} failed ({verify_method})"
    return {
        "ok": False,
        "action": action_name,
        "engine": last_engine,
        "attempts": attempts,
        "verify_method": verify_method,
        "fallback_used": len(engine_list) > 1,
        "note": note,
    }
