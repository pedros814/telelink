"""Shared terminal capability detection for TeleLink."""

from __future__ import annotations

import os
import sys


def fix_stdio() -> None:
    """UTF-8 + ANSI colors on Windows consoles."""
    if sys.platform != "win32":
        return
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def unicode_capable() -> bool:
    """True only in terminals that reliably render Unicode box/banner art."""
    if os.environ.get("TELELINK_ASCII") == "1":
        return False
    return bool(
        os.environ.get("WT_SESSION")
        or os.environ.get("TERM_PROGRAM") == "vscode"
        or os.environ.get("TELELINK_UNICODE_BANNER") == "1"
    )


def color_capable() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("TELELINK_COLOR") == "1":
        return True
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def banner_is_valid(text: str) -> bool:
    """Reject mojibake / corrupted filled banners."""
    if not text.strip():
        return False
    if "Γ" in text and any(ch in text for ch in "ûòéöñ"):
        return False
    return True


def terminal_width(*, default: int = 80) -> int:
    return terminal_size(default=default)[0]


def terminal_size(*, default: int = 80, default_rows: int = 24) -> tuple[int, int]:
    try:
        import shutil

        size = shutil.get_terminal_size(fallback=(default, default_rows))
        return max(40, size.columns), max(10, size.lines)
    except Exception:
        return default, default_rows
