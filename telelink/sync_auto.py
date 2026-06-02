"""Background Phone Link re-sync while TeleLink shell is running."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from telelink.duration import parse_duration

log = logging.getLogger(__name__)

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def auto_sync_enabled(config: dict[str, Any]) -> bool:
    sync = config.get("sync") or {}
    return sync.get("auto_sync", True) is not False


def auto_sync_interval_seconds(config: dict[str, Any]) -> int:
    sync = config.get("sync") or {}
    raw = sync.get("auto_sync_interval", "15m")
    secs = parse_duration(raw)
    return max(60, secs if secs else 900)


def run_auto_sync(config: dict[str, Any]) -> bool:
    """Run one background sync cycle. Returns True if sync ran."""
    if not auto_sync_enabled(config):
        return False
    try:
        from telelink.session import get_session
        from telelink.sync import run_full_sync

        run_full_sync(get_session(), force=True, quiet=True)
        return True
    except Exception as exc:
        log.debug("auto-sync failed: %s", exc)
        return False


def start_sync_daemon(config_loader: Callable[[], dict[str, Any]]) -> None:
    """Poll Phone Link sources on sync.auto_sync_interval (default 15m)."""
    global _thread, _started

    if not auto_sync_enabled(config_loader()):
        return

    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()

        def _loop() -> None:
            while not _stop.is_set():
                cfg = config_loader()
                interval = auto_sync_interval_seconds(cfg)
                if _stop.wait(interval):
                    break
                try:
                    cfg = config_loader()
                    if auto_sync_enabled(cfg):
                        run_auto_sync(cfg)
                except Exception:
                    pass

        _thread = threading.Thread(
            target=_loop,
            name="telelink-sync-auto",
            daemon=True,
        )
        _thread.start()


def stop_sync_daemon() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
