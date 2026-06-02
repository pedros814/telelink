"""Periodic missed-call reminder (interactive shell) + badge on intake reminder."""

from __future__ import annotations

import threading
from typing import Any, Callable

from telelink import chalk, ink_ui, pretty
from telelink.call_log import call_log_enabled, call_log_path
from telelink.config import load_config
from telelink.duration import parse_duration
from telelink.intake_runtime import is_intake_running

MARGIN = ink_ui.MARGIN

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def _remind_interval_seconds(config: dict[str, Any]) -> int:
    calls = config.get("calls") or {}
    raw = calls.get("remind_interval", "10m")
    secs = parse_duration(raw)
    return secs if secs else 600


def missed_call_count(config: dict[str, Any] | None = None) -> int:
    config = config or load_config()
    if not call_log_enabled(config):
        return 0
    from telelink.call_log import CallLogStore

    store = CallLogStore(call_log_path(config))
    return store.count_missed()


def format_missed_badge(count: int) -> str:
    if count <= 0:
        return ""
    label = "missed call" if count == 1 else "missed calls"
    return f"{count} {label}"


def emit_missed_calls_reminder(
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Print missed-call count when > 0."""
    config = config or load_config()
    if not call_log_enabled(config):
        if force:
            pretty.warn("call log is disabled in config.yaml")
        return False

    count = missed_call_count(config)
    if count <= 0:
        if force:
            pretty.info("CALLS", "no missed calls in the log")
        return False

    label = "call" if count == 1 else "calls"
    pretty.info("CALLS", f"{count} missed {label}")
    print(
        f"{MARGIN}{chalk.muted('View:')} {chalk.command('missed')} "
        f"{chalk.muted('· all calls:')} {chalk.command('calls')}",
        flush=True,
    )
    return True


def intake_reminder_missed_suffix(config: dict[str, Any]) -> str:
    """Short suffix for intake uptime reminder line."""
    if not call_log_enabled(config):
        return ""
    count = missed_call_count(config)
    if count <= 0:
        return ""
    return f" · {format_missed_badge(count)}"


def start_calls_remind_daemon(config_loader: Callable[[], dict[str, Any]]) -> None:
    global _thread, _started

    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()

        def _loop() -> None:
            while not _stop.is_set():
                try:
                    cfg = config_loader()
                    interval = _remind_interval_seconds(cfg)
                    if _stop.wait(interval):
                        break
                    if not call_log_enabled(cfg):
                        continue
                    # Remind when intake is running OR there are missed calls.
                    if is_intake_running(cfg) or missed_call_count(cfg) > 0:
                        emit_missed_calls_reminder(cfg)
                except Exception:
                    pass

        _thread = threading.Thread(
            target=_loop,
            name="telelink-calls-remind",
            daemon=True,
        )
        _thread.start()


def stop_calls_remind_daemon() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
