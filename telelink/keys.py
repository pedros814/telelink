"""Raw terminal key input — Ctrl+B back, Ctrl+V paste, clean Ctrl+C."""

from __future__ import annotations

import subprocess
import sys

BACK = "__statey_back__"
HELP = "__statey_help__"


def read_line(*, echo: bool = True) -> str:
    if sys.platform == "win32":
        return _read_line_windows(echo=echo)
    return _read_line_posix(echo=echo)


def _clipboard_text() -> str:
    """Best-effort clipboard read (no extra dependencies)."""
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=flags,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    for cmd in (
        ["pbpaste"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["wl-paste", "--no-newline"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    return ""


def _insert_paste(buf: list[str], *, echo: bool) -> None:
    text = _clipboard_text()
    if not text:
        return
    for ch in text:
        if ch == "\r":
            ch = "\n"
        buf.append(ch)
        if echo:
            sys.stdout.write(ch)
    if echo:
        sys.stdout.flush()


def _drain_key_buffer() -> None:
    """Drop stale keypresses (phantom digits often bleed into the next command)."""
    if sys.platform != "win32":
        return
    import msvcrt

    while msvcrt.kbhit():
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()


def _read_line_windows(*, echo: bool) -> str:
    import msvcrt

    _drain_key_buffer()
    buf: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch == "\x03":  # Ctrl+C
            if echo:
                sys.stdout.write("^C\n")
                sys.stdout.flush()
            raise KeyboardInterrupt
        if ch == "\x02":  # Ctrl+B
            if echo:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return BACK
        if ch == "\x16":  # Ctrl+V
            _insert_paste(buf, echo=echo)
            continue
        if ch in "\r\n":
            if echo:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return "".join(buf)
        if ch == "\x08":
            if not buf:
                if echo:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                return HELP
            buf.pop()
            if echo:
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch in ("\x00", "\xe0"):
            ext = msvcrt.getwch()
            # Shift+Insert paste in classic Windows console
            if ext in ("S", "s", "R", "r"):
                _insert_paste(buf, echo=echo)
            continue
        buf.append(ch)
        if echo:
            sys.stdout.write(ch)
            sys.stdout.flush()


def _read_line_posix(*, echo: bool) -> str:
    try:
        import termios
        import tty
    except ImportError:
        return input()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x03":
                if echo:
                    sys.stdout.write("^C\n")
                    sys.stdout.flush()
                raise KeyboardInterrupt
            if ch == "\x02":
                if echo:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                return BACK
            if ch == "\x16":  # Ctrl+V
                _insert_paste(buf, echo=echo)
                continue
            if ch in "\r\n":
                if echo:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                return "".join(buf)
            if ch in ("\x7f", "\x08"):
                if not buf and ch == "\x08":
                    if echo:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    return HELP
                if buf:
                    buf.pop()
                    if echo:
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                continue
            buf.append(ch)
            if echo:
                sys.stdout.write(ch)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


_CTRL_HANDLER = None


def install_console_ctrl_handler(on_stop) -> None:
    """Handle Ctrl+C / Ctrl+Break without polling msvcrt (avoids console freezes)."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    @HandlerRoutine
    def _handler(ctrl_type: int) -> bool:
        if ctrl_type in (0, 1):  # CTRL_C_EVENT, CTRL_BREAK_EVENT
            on_stop()
            return True
        return False

    global _CTRL_HANDLER
    _CTRL_HANDLER = _handler
    kernel32.SetConsoleCtrlHandler(_handler, True)


def listen_for_ctrl_c(stop, *, on_stop=None) -> None:
    """Register Ctrl+C handler for blocking listen/watcher loops."""
    if sys.platform == "win32":
        def _fire() -> None:
            stop.set()
            if on_stop:
                on_stop()

        install_console_ctrl_handler(_fire)
        return

    import signal

    def _sigint(*_) -> None:
        stop.set()
        if on_stop:
            on_stop()

    try:
        signal.signal(signal.SIGINT, _sigint)
    except Exception:
        pass
