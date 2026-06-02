"""Periodic reminder of pending scheduled calendar events (interactive shell)."""

from __future__ import annotations

import threading
from typing import Any, Callable

from telelink import chalk, ink_ui, pretty
from telelink.config import load_config
from telelink.duration import format_duration, parse_duration

MARGIN = ink_ui.MARGIN

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def _remind_interval_seconds(config: dict[str, Any]) -> int:
    cal = config.get("calendar") or {}
    raw = cal.get("remind_interval", "15m")
    secs = parse_duration(raw)
    return secs if secs else 900


def emit_calendar_pending_reminder(
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Print how many events are scheduled to fire (only if count > 0)."""
    config = config or load_config()
    cal = config.get("calendar") or {}
    if cal.get("enabled", True) is False:
        if force:
            pretty.warn("calendar is disabled in config.yaml")
        return False

    from telelink.session import get_session

    count = get_session().db.calendar_count_pending()
    if count <= 0:
        if force:
            pretty.info("CALENDAR", "no scheduled events pending")
        return False

    label = "event" if count == 1 else "events"
    pretty.info("CALENDAR", f"{count} scheduled {label} waiting to fire")
    print(
        f"{MARGIN}{chalk.muted('View:')} {chalk.command('calendar')} "
        f"{chalk.muted('· cancel:')} {chalk.command('calendar delete <name>')}",
        flush=True,
    )
    return True


def start_calendar_remind_daemon(config_loader: Callable[[], dict[str, Any]]) -> None:
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
                    cal = cfg.get("calendar") or {}
                    if cal.get("enabled", True) is False:
                        continue
                    emit_calendar_pending_reminder(cfg)
                except Exception:
                    pass

        _thread = threading.Thread(
            target=_loop,
            name="telelink-calendar-remind",
            daemon=True,
        )
        _thread.start()


def stop_calendar_remind_daemon() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
