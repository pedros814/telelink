"""Minimal ink-style layouts — baby blue theme."""

from __future__ import annotations

from telelink import chalk

MARGIN = "   "
TOP_PAD = 1  # blank lines above banner + art

HINT_BARS = (
    "ctrl+h help",
    "ctrl+b back",
    "ctrl+c cancel",
)


def _strip_block(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def indent(text: str, *, margin: str = MARGIN) -> str:
    if not text:
        return text
    return "\n".join(margin + line if line else "" for line in text.splitlines())


def side_by_side(left: str, right: str, *, gap: int = 4) -> str:
    """Banner left, art right — fixed-width art column, top-aligned."""
    left_lines = _strip_block(left).splitlines() or [""]
    right_lines = _strip_block(right).splitlines() or [""]

    left_w = max(len(line) for line in left_lines)
    art_w = max(len(line) for line in right_lines) if right_lines else 0
    right_lines = [line.ljust(art_w) for line in right_lines]

    height = max(len(left_lines), len(right_lines))
    left_lines = left_lines + [""] * (height - len(left_lines))
    right_lines = right_lines + [""] * (height - len(right_lines))

    spacer = " " * gap
    return "\n".join(
        left_lines[i].ljust(left_w) + spacer + right_lines[i] for i in range(height)
    )


def hint_bars(*, gap: str = "  ") -> str:
    return gap.join(chalk.hint_bar(label) for label in HINT_BARS)


def boot_screen(
    banner: str,
    *,
    side_art: str = "",
    margin: str = MARGIN,
) -> str:
    from telelink.terminal import terminal_width

    banner_plain = _strip_block(banner.rstrip("\n"))
    header = banner_plain

    if side_art.strip():
        combined = side_by_side(banner_plain, side_art.strip())
        if max(len(line) for line in combined.splitlines()) <= terminal_width() - len(margin):
            header = combined

    if _enabled_banner():
        header = "\n".join(chalk.baby(line) if line.strip() else line for line in header.splitlines())

    footer = indent(hint_bars(), margin=margin)
    parts: list[str] = [""] * TOP_PAD
    parts.extend([indent(header, margin=margin), "", footer])
    return "\n".join(parts)


def _enabled_banner() -> bool:
    from telelink.terminal import color_capable

    return color_capable()
