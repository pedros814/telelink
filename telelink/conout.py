"""Serialize console output on the asyncio loop (safe on Windows consoles)."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Any, Callable

_out: ConsoleOut | None = None


class ConsoleOut:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[tuple[Callable[..., Any], tuple, dict]] | None = None
        self._task: asyncio.Task | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue = asyncio.Queue()

    def start(self) -> asyncio.Task:
        if self._loop is None or self._queue is None:
            raise RuntimeError("ConsoleOut.bind() before start()")
        self._task = self._loop.create_task(self._drain())
        return self._task

    async def _drain(self) -> None:
        assert self._queue is not None
        while True:
            fn, args, kwargs = await self._queue.get()
            try:
                if getattr(fn, "_telelink_console_slow", False):
                    await asyncio.to_thread(fn, *args, **kwargs)
                else:
                    fn(*args, **kwargs)
            except Exception:
                pass

    def schedule(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            fn(*args, **kwargs)
            return
        try:
            running = asyncio.get_running_loop()
            if running is loop and threading.current_thread() is threading.main_thread():
                fn(*args, **kwargs)
                return
        except RuntimeError:
            pass
        loop.call_soon_threadsafe(queue.put_nowait, (fn, args, kwargs))


def get_console_out() -> ConsoleOut:
    global _out
    if _out is None:
        _out = ConsoleOut()
    return _out


def prepare_watcher_console() -> None:
    """Watcher window: UTF-8, unbuffered stdout, visible cursor, window title."""
    from telelink.terminal import fix_stdio

    fix_stdio()
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW("TeleLink Watcher")
        except Exception:
            pass
        from telelink.watcher_console_nudge import disable_quick_edit_mode

        disable_quick_edit_mode()


def prepare_ars_console() -> None:
    """ARS window: UTF-8, unbuffered stdout, title from TELELINK_ARS_SESSION."""
    from telelink.terminal import fix_stdio

    fix_stdio()
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass
    if sys.platform == "win32":
        session = (os.getenv("TELELINK_ARS_SESSION") or "").strip()
        contact = (os.getenv("TELELINK_ARS_CONTACT") or "").strip()
        title = "TeleLink ARS"
        if session:
            title = f"TeleLink ARS — {session}"
            if contact:
                title = f"{title} ({contact})"
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass
        from telelink.watcher_console_nudge import disable_quick_edit_mode

        disable_quick_edit_mode()
