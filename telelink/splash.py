"""Launch splash — loading screen only (art lives on main boot screen)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Side art for boot screen (was text-art at repo root)
_TEXT_ART_RAW = """\
──▄▄██████▄▄
▄██▀▄█▄▄█▄▀██▄
▀▀▀▄██▀▀██▄▀▀▀
─▄███─██─███▄
─█████▄▄█████\
"""


def _crop_art(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []
    left = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return [line[left:].rstrip() if line.strip() else "" for line in lines]


def normalize_art(art: str) -> str:
    """Trim padding and align columns — no scaling."""
    lines = _crop_art([line.rstrip("\n\r") for line in art.splitlines()])
    if not lines:
        return ""
    max_w = max(len(line) for line in lines if line.strip())
    return "\n".join(line.ljust(max_w) if line.strip() else line for line in lines)


def load_text_art() -> str:
    if not _TEXT_ART_RAW.strip():
        return ""
    return normalize_art(_TEXT_ART_RAW)


def show_launch_splash(*, duration: float = 1.0) -> None:
    """Brief loading spinner before the main shell."""
    from telelink.config import load_config
    from telelink.ora import ora

    with ora("Loading TeleLink", kind="boot", min_duration=duration):
        load_config()
