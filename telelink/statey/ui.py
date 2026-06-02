"""Statey terminal UI — breadcrumbs, nav bar, screen chrome."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from telelink import chalk, ink_ui

if TYPE_CHECKING:
    from telelink.statey.engine import Statey


def render_prompt_path(path: str) -> None:
    parts = [p.strip() for p in path.split("›")]
    sys.stdout.write(ink_ui.MARGIN)
    if len(parts) <= 1:
        sys.stdout.write(f"{chalk.prompt(parts[0])} {chalk.prompt('>')} ")
    else:
        head = chalk.prompt(parts[0])
        trail = chalk.muted(" › ".join(parts[1:]))
        sys.stdout.write(f"{head} {trail} {chalk.prompt('>')} ")
    sys.stdout.flush()


def nav_bar(*, at_root: bool, in_flow: bool) -> str:
    if at_root and not in_flow:
        return ""
    keys = []
    if in_flow or not at_root:
        keys.append(chalk.baby("back"))
    keys.extend([chalk.baby("cancel"), chalk.baby("help")])
    return chalk.muted(" · ".join(keys))


def help_body(statey: Statey) -> None:
    """Help text only — no screen title (prompt already shows context)."""
    screen = statey.current
    for line in screen.help_lines:
        print(f"{ink_ui.MARGIN}{chalk.plain(line)}", flush=True)
    if screen.help_lines:
        print(flush=True)


def screen_header(statey: Statey) -> None:
    screen = statey.current
    bar = nav_bar(at_root=statey.at_root, in_flow=statey.in_flow)
    title = chalk.label(screen.title)
    if bar:
        print(f"{ink_ui.MARGIN}{title}  {bar}", flush=True)
    else:
        print(f"{ink_ui.MARGIN}{title}", flush=True)
    for line in screen.help_lines:
        print(f"{ink_ui.MARGIN}{chalk.plain(line)}", flush=True)
    if screen.help_lines:
        print(flush=True)


def menu(title: str, items: list[tuple[str, str]]) -> None:
    key_w = max((len(label) for label, _ in items), default=0)
    print(f"{ink_ui.MARGIN}{chalk.label(title)}", flush=True)
    for label, desc in items:
        key = chalk.baby(label.ljust(key_w))
        print(f"{ink_ui.MARGIN}{key}  {chalk.plain(desc)}", flush=True)
    print(f"{ink_ui.MARGIN}{ink_ui.hint_bars()}", flush=True)
    print(flush=True)
