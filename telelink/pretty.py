"""Pretty CLI messages — baby blue theme."""

from __future__ import annotations

import sys

from telelink import chalk

_PREVIEW_INDENT = "           "
_PREVIEW_WARNED = False


def _print(*parts: str) -> None:
    line = " ".join(p for p in parts if p)
    _print_line(line)


def _print_line(line: str) -> None:
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((line + "\n").encode(enc, errors="replace"))
        sys.stdout.flush()


def info(label: str, message: str = "") -> None:
    badge = chalk.badge(label)
    body = chalk.value(message) if message else ""
    _print(badge, body)


def loading(label: str, message: str = "") -> None:
    info(label, message)


def warn(message: str, *, label: str = "WARN") -> None:
    badge = chalk.badge(label)
    _print(badge, chalk.muted(message))


def error(message: str, *, label: str = "ERROR", exit_code: int | None = 1) -> None:
    badge = chalk.badge(label)
    _print(badge, chalk.value(message))
    if exit_code is not None:
        raise SystemExit(exit_code)


def command(text: str) -> str:
    return chalk.command(text)


def link(url: str) -> str:
    return chalk.link(url)


def task(flag: str, tag: str, who: str, text: str) -> None:
    badge = chalk.badge("CAUGHT")
    detail = " ".join(
        [
            chalk.value(f"[{flag}]"),
            chalk.value(f"[{tag}]"),
            chalk.value(who + ":"),
            chalk.value(text),
        ]
    )
    _print(badge, detail)


def path(text: str) -> None:
    _print_line(f"{_PREVIEW_INDENT}{chalk.muted('->')} {chalk.value(text)}")


def attachment_preview(
    image_path: str,
    *,
    meta: dict | None = None,
    config: dict | None = None,
) -> None:
    """Watcher-only inline attachment preview (half-block ANSI via Pillow)."""
    # Drained on a worker thread — Pillow must not block the asyncio loop (WinRT polls).
    from pathlib import Path

    from telelink.terminal import terminal_width, unicode_capable
    from telelink.terminal_image import preview_enabled, preview_options, render_file

    global _PREVIEW_WARNED
    if not preview_enabled(config):
        preview_cfg = ((config or {}).get("media") or {}).get("preview") or {}
        if (
            not _PREVIEW_WARNED
            and isinstance(preview_cfg, dict)
            and preview_cfg.get("enabled", True) is not False
        ):
            _PREVIEW_WARNED = True
            warn(
                "photo preview unavailable (needs Pillow + color terminal)",
                label="PREVIEW",
            )
        return

    src = Path(image_path)
    if not src.is_file():
        return

    opts = preview_options(config)
    block = render_file(
        src,
        width=opts.get("width", "58%"),
        height=opts.get("height"),
        max_edge=int(opts.get("max_edge", 960)),
        config=config,
    )
    if not block:
        return

    meta = meta or {}
    name = meta.get("filename") or src.name
    kind = meta.get("media_kind") or "image"
    w, h = meta.get("width"), meta.get("height")
    dot = " | " if not unicode_capable() else " · "
    mid = "x" if not unicode_capable() else "×"
    dims = f"{dot}{w}{mid}{h}" if w and h else ""

    _print_line(f"{_PREVIEW_INDENT}{chalk.badge('PHOTO')}{chalk.muted(f' {name}{dims}{dot}{kind}')}")

    rule_w = min(52, max(28, terminal_width() - len(_PREVIEW_INDENT) - 4))
    rule = chalk.muted("─" * rule_w) if unicode_capable() else chalk.muted("-" * rule_w)
    _print_line(f"{_PREVIEW_INDENT}{rule}")
    for line in block.splitlines():
        _print_line(f"{_PREVIEW_INDENT}{line}")


attachment_preview._telelink_console_slow = True  # noqa: SLF001


def section(title: str) -> str:
    return chalk.label(title)
