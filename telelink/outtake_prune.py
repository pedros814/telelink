"""Background GitHub outtake cleanup for the interactive shell."""

from __future__ import annotations

import threading
from typing import Any, Callable

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def start_outtake_prune_daemon(config_loader: Callable[[], dict[str, Any]]) -> None:
    """Poll GitHub and delete expired outtake uploads (daemon thread)."""
    global _thread, _started

    config = config_loader()
    from telelink.outtake_share import outtake_auto_delete_seconds, prune_outtake_github

    if not outtake_auto_delete_seconds(config):
        return

    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()

        def _loop() -> None:
            from telelink.outtake_share import (
                outtake_auto_delete_poll_seconds,
                outtake_auto_delete_seconds,
            )

            while not _stop.is_set():
                interval = outtake_auto_delete_poll_seconds(config_loader())
                if _stop.wait(interval):
                    break
                try:
                    cfg = config_loader()
                    if outtake_auto_delete_seconds(cfg):
                        prune_outtake_github(cfg)
                except Exception:
                    pass

        _thread = threading.Thread(
            target=_loop,
            name="telelink-outtake-prune",
            daemon=True,
        )
        _thread.start()


def stop_outtake_prune_daemon() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
