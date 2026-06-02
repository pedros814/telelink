"""Baby-blue terminal theme (chalk-style API)."""

from __future__ import annotations

import re

_RESET = "\033[0m"
_BABY = "\033[38;5;117m"
_LIGHT = "\033[38;5;153m"  # same shade as hint-bar square backgrounds
_VALUE = "\033[38;5;195m"
_MUTED = "\033[38;5;110m"
_WHITE = "\033[97m"


def _enabled() -> bool:
    from telelink.terminal import color_capable

    return color_capable()


class _Style:
    __slots__ = ("_open", "_close")

    def __init__(self, *codes: str, close: str = _RESET) -> None:
        self._open = "".join(codes)
        self._close = close

    def __call__(self, text: str) -> str:
        if not _enabled() or not self._open:
            return text
        return f"{self._open}{text}{self._close}"

    def bold(self) -> _Style:
        return _Style("\033[1m", self._open, close=self._close)

    def dim(self) -> _Style:
        return _Style("\033[2m", self._open, close=self._close)

    def inverse(self) -> _Style:
        return _Style("\033[7m", self._open, close=self._close)


def _style(*codes: str) -> _Style:
    return _Style(*codes)


# Primary palette — baby blue accents, white for normal text.
plain = _Style()
white = _style(_WHITE)
baby = _style(_BABY)
light = _style(_LIGHT)
value = _style(_VALUE)
muted = _style(_MUTED)
label = _style(_BABY, "\033[1m")
prompt = light
# Background badge — avoids inverse (\033[7m) which flashes green on Windows cmd.
# Slightly lighter baby-blue background for hint / badge squares.
badge_fill = _style("\033[48;5;153m", "\033[38;5;16m", "\033[1m")

bold = _Style("\033[1m")
dim = _Style("\033[2m")
inverse = _Style("\033[7m")

# Back-compat aliases — accent colors map to baby palette.
black = baby
red = baby
green = baby
yellow = baby
blue = baby
cyan = baby
magenta = baby
gray = muted
grey = muted
normal = white


def badge(text: str) -> str:
    return badge_fill(f" {text} ")


def hint_bar(text: str) -> str:
    """Full-width hint strip — same square bg as LISTEN / TASK badges."""
    return badge_fill(f" {text} ")


def command(text: str) -> str:
    return value(text)


def link(text: str) -> str:
    return value(text)


def strip(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
