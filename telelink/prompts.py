"""Interactive prompts — baby blue theme."""

from __future__ import annotations

import sys
from typing import Any

from telelink import chalk
from telelink.keys import BACK, read_line


def text(message: str, *, initial: str = "") -> str:
    hint = chalk.muted(f"({initial})") if initial else ""
    sys.stdout.write(f"{chalk.baby('?')} {message} {hint} ".strip() + " ")
    sys.stdout.flush()
    value = read_line().strip()
    return value or initial


def confirm(message: str, *, initial: bool = True) -> bool:
    suffix = chalk.muted("Y/n" if initial else "y/N")
    sys.stdout.write(f"{chalk.baby('?')} {message} {suffix} ")
    sys.stdout.flush()
    value = read_line().strip().lower()
    if not value:
        return initial
    return value in ("y", "yes")


def confirm_choice(
    *,
    title: str,
    details: list[str] | None = None,
    yes_label: str = "Yes — continue",
    no_label: str = "No — cancel",
    warn_icon: bool = True,
) -> bool:
    """Numbered yes/no prompt (1 = yes, 2 = no) — same style as GitHub outtake confirm."""
    from telelink import ink_ui

    m = ink_ui.MARGIN
    print(flush=True)
    if warn_icon:
        print(f"{m}{chalk.baby('⚠︎')}  {chalk.label(title)}", flush=True)
    else:
        print(f"{m}{chalk.label(title)}", flush=True)
    for line in details or []:
        print(f"{m}{chalk.muted(line)}", flush=True)
    print(flush=True)
    print(f"{m}{chalk.baby('1')}  {chalk.plain(yes_label)}", flush=True)
    print(f"{m}{chalk.baby('2')}  {chalk.plain(no_label)}", flush=True)
    print(flush=True)

    if not sys.stdin.isatty():
        from telelink import pretty

        pretty.warn("confirmation needs a terminal — enter 1 or 2")
        return False

    while True:
        sys.stdout.write(
            f"{m}{chalk.prompt('Choice')} {chalk.prompt('1')} "
            f"{chalk.muted('/')} {chalk.prompt('2')} {chalk.prompt('>')} "
        )
        sys.stdout.flush()
        raw = read_line().strip().lower()
        if raw in ("1", "yes", "y"):
            return True
        if raw in ("2", "no", "n", "cancel", "c", "abort", "a"):
            return False
        if not raw:
            return False
        print(f"{m}{chalk.muted('enter 1 or 2')}", flush=True)


def select(message: str, choices: list[str], *, initial: int = 0) -> str:
    print(f"{chalk.baby('?')} {message}")
    for i, choice in enumerate(choices):
        mark = chalk.baby(">") if i == initial else " "
        name = chalk.value(choice) if i == initial else chalk.muted(choice)
        print(f"  {mark} {name}")
    print(chalk.muted("  enter a number"))
    sys.stdout.write(f"{chalk.baby('?')} choice ")
    sys.stdout.flush()
    raw = read_line().strip()
    if raw.isdigit():
        idx = int(raw)
        if 0 <= idx < len(choices):
            return choices[idx]
    return choices[initial] if choices else ""


def ask(spec: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    items = spec if isinstance(spec, list) else [spec]
    answers: dict[str, Any] = {}
    for item in items:
        kind = item.get("type", "text")
        name = item.get("name", "value")
        message = item.get("message", name)
        if kind == "confirm":
            answers[name] = confirm(message, initial=bool(item.get("initial", True)))
        elif kind == "select":
            choices = [
                c.get("title", c.get("value", str(c))) if isinstance(c, dict) else str(c)
                for c in item.get("choices", [])
            ]
            answers[name] = select(message, choices, initial=int(item.get("initial", 0)))
        else:
            answers[name] = text(message, initial=str(item.get("initial", "")))
    return answers


def shell_line(*, prefix: str = "telelink", prompt: str | None = None) -> str:
    from telelink.statey.ui import render_prompt_path

    label = prompt if prompt is not None else prefix
    render_prompt_path(label)
    try:
        return read_line()
    except EOFError:
        return ""
