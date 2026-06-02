"""UTF-8-safe JSON printing for CLI and agents."""

from __future__ import annotations

import json
import sys
from typing import Any


def print_json(value: Any, *, indent: int | None = 2) -> None:
    """Write JSON to stdout (UTF-8 on Windows)."""
    from telelink.terminal import fix_stdio

    fix_stdio()
    text = json.dumps(value, indent=indent, ensure_ascii=False)
    if indent is None:
        text += "\n"
    else:
        text += "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
