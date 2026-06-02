"""Ora-style terminal spinners (https://github.com/sindresorhus/ora + cli-spinners)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from telelink import chalk

ROOT = Path(__file__).resolve().parent.parent
_SPINNERS_FILE = ROOT / "assets" / "ora-spinners.json"

_SPINNERS: dict[str, dict] | None = None

# Ora defaults: dots (unicode), line (plain Windows cmd).
_DEFAULT_UTF8 = "dots"
_DEFAULT_ASCII = "line"
_BOOT = "dots"
_SCAN = "bouncingBar"
_LOAD = "dots"


def _load_spinners() -> dict[str, dict]:
    global _SPINNERS
    if _SPINNERS is None:
        if _SPINNERS_FILE.exists():
            _SPINNERS = json.loads(_SPINNERS_FILE.read_text(encoding="utf-8"))
        else:
            _SPINNERS = {
                "dots": {"interval": 80, "frames": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]},
                "line": {"interval": 130, "frames": ["-", "\\", "|", "/"]},
            }
    return _SPINNERS


def unicode_terminal() -> bool:
    from telelink.terminal import unicode_capable

    return unicode_capable()


def default_spinner() -> str:
    return _DEFAULT_UTF8 if unicode_terminal() else _DEFAULT_ASCII


def _resolve_spinner(name: str | None, *, kind: str) -> tuple[float, list[str]]:
    catalog = _load_spinners()
    if name is None:
        if kind == "boot":
            name = _BOOT
        elif kind == "scan":
            name = _SCAN
        else:
            name = _LOAD
        if not unicode_terminal() and name not in catalog:
            name = _DEFAULT_ASCII
        elif name not in catalog:
            name = default_spinner()
    if name not in catalog:
        name = default_spinner()
    spec = catalog[name]
    interval = float(spec["interval"]) / 1000.0
    return interval, list(spec["frames"])


class Ora:
    """Minimal ora-compatible spinner for TeleLink."""

    def __init__(
        self,
        text: str,
        *,
        spinner: str | None = None,
        prefix: str = "",
        kind: str = "load",
        stream=None,
    ) -> None:
        self.text = text
        self.spinner_name = spinner
        self.prefix = prefix
        self.kind = kind
        self.stream = stream or sys.stdout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor_hidden = False

    def _set_cursor_visible(self, visible: bool) -> None:
        if sys.platform == "win32":
            try:
                import ctypes

                class CONSOLE_CURSOR_INFO(ctypes.Structure):
                    _fields_ = [("dwSize", ctypes.c_uint32), ("bVisible", ctypes.c_int)]

                handle = ctypes.windll.kernel32.GetStdHandle(-11)
                ci = CONSOLE_CURSOR_INFO()
                ctypes.windll.kernel32.GetConsoleCursorInfo(handle, ctypes.byref(ci))
                ci.bVisible = int(visible)
                ctypes.windll.kernel32.SetConsoleCursorInfo(handle, ctypes.byref(ci))
            except Exception:
                pass
        else:
            try:
                self.stream.write("\033[?25h" if visible else "\033[?25l")
                self.stream.flush()
            except Exception:
                pass

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except UnicodeEncodeError:
            enc = getattr(self.stream, "encoding", None) or "utf-8"
            self.stream.write(text.encode(enc, errors="replace").decode(enc))
            self.stream.flush()

    def _loop(self) -> None:
        interval, frames = _resolve_spinner(self.spinner_name, kind=self.kind)
        idx = 0
        while not self._stop.is_set():
            frame = frames[idx % len(frames)]
            idx += 1
            self._write(f"\r{self.prefix}{chalk.baby(frame)} {chalk.baby(self.text)}")
            if self._stop.wait(interval):
                break

    def start(self) -> Ora:
        self._set_cursor_visible(False)
        self._cursor_hidden = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        time.sleep(0.05)
        return self

    def stop(self, *, clear: bool = True) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._cursor_hidden:
            self._set_cursor_visible(True)
            self._cursor_hidden = False
        if clear:
            self._write("\r" + " " * 100 + "\r\033[0m")

    def __enter__(self) -> Ora:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()


@contextmanager
def ora(
    text: str,
    *,
    spinner: str | None = None,
    prefix: str = "",
    kind: str = "load",
    min_duration: float = 0.0,
) -> Iterator[None]:
    s = Ora(text, spinner=spinner, prefix=prefix, kind=kind)
    started = time.monotonic()
    try:
        s.start()
        yield
    finally:
        remaining = min_duration - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        s.stop(clear=True)
