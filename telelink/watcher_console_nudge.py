"""Watcher console keepalive — disable Quick Edit freeze + periodic Enter nudge."""

from __future__ import annotations

import asyncio
import sys
from typing import Any


def disable_quick_edit_mode() -> None:
    """Stop accidental text selection from pausing the watcher process (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        if handle in (0, -1):
            return
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        enable_quick_edit = 0x0040
        kernel32.SetConsoleMode(handle, mode.value & ~enable_quick_edit)
    except Exception:
        pass


def press_console_enter() -> None:
    """Inject Enter into this process console input (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)
        if handle in (0, -1):
            return

        class CHAR_UNION(ctypes.Union):
            _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wintypes.BOOL),
                ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD),
                ("wVirtualScanCode", wintypes.WORD),
                ("uChar", CHAR_UNION),
                ("dwControlKeyState", wintypes.DWORD),
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [("EventType", wintypes.WORD), ("Event", KEY_EVENT_RECORD)]

        def _key(*, down: bool) -> INPUT_RECORD:
            rec = INPUT_RECORD()
            rec.EventType = 0x0001  # KEY_EVENT
            ev = rec.Event
            ev.bKeyDown = down
            ev.wRepeatCount = 1
            ev.wVirtualKeyCode = 0x0D  # VK_RETURN
            ev.uChar.UnicodeChar = "\r" if down else "\x00"
            return rec

        events = (INPUT_RECORD * 2)(_key(down=True), _key(down=False))
        written = wintypes.DWORD()
        kernel32.WriteConsoleInputW(handle, events, 2, ctypes.byref(written))
    except Exception:
        pass


def watcher_console_nudge_interval_seconds(config: dict[str, Any]) -> float:
    listener = config.get("listener") or {}
    if listener.get("console_nudge", True) is False:
        return 0.0
    if isinstance(listener.get("console_nudge"), str):
        if listener["console_nudge"].strip().lower() in ("false", "off", "0", "no"):
            return 0.0
    raw = listener.get("console_nudge_interval_seconds")
    if raw is None:
        from telelink.duration import parse_duration

        parsed = parse_duration(listener.get("console_nudge_interval", "45s"))
        raw = parsed if parsed else 45
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 45.0


async def watcher_console_nudge_loop(stop: asyncio.Event, interval_seconds: float) -> None:
    """Press Enter in the watcher console every interval_seconds until stop."""
    interval = max(1.0, float(interval_seconds))
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        await asyncio.to_thread(press_console_enter)
