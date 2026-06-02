"""Statey shell loop for TeleLink."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from telelink.keys import BACK, HELP
from telelink.terminal import banner_is_valid, fix_stdio, unicode_capable

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

_FALLBACK_BANNER = r"""
  _____    _      _     _       _    
 |_   _|__| | ___| |   (_)_ __ | | __
   | |/ _ \ |/ _ \ |   | | '_ \| |/ /
   | |  __/ |  __/ |___| | | | |   < 
   |_|\___|_|\___|_____|_|_| |_|_|\_\
""".strip(
    "\n"
)


def _fix_stdio() -> None:
    fix_stdio()


def _say(text: str = "") -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        from telelink import chalk

        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(chalk.strip(text).encode(enc, errors="replace").decode(enc), flush=True)


def load_banner() -> str:
    if unicode_capable():
        filled = ASSETS / "banner.filled.txt"
        if filled.exists():
            raw = filled.read_text(encoding="utf-8", errors="replace")
            raw = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", raw)
            if banner_is_valid(raw) and len(raw.strip()) > 20:
                return raw.strip("\n")

    plain = ASSETS / "banner.txt"
    if plain.exists():
        raw = plain.read_text(encoding="utf-8", errors="replace")
        raw = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", raw)
        if len(raw.strip()) > 10:
            return raw.strip("\n")

    return _FALLBACK_BANNER


def run_shell() -> int:
    from telelink import chalk, ink_ui, prompts
    from telelink.splash import load_text_art, show_launch_splash
    from telelink.statey.app import build_statey

    _fix_stdio()
    os.system("cls" if sys.platform == "win32" else "clear")

    show_launch_splash(duration=1.0)

    os.system("cls" if sys.platform == "win32" else "clear")
    banner = load_banner()

    _say(
        ink_ui.boot_screen(
            banner,
            side_art=load_text_art(),
        )
    )
    _say()

    statey = build_statey()

    from telelink import pretty
    from telelink.listener_spawn import auto_start_watcher_if_configured

    match auto_start_watcher_if_configured(root=ROOT):
        case "started":
            pretty.info("WATCHER", "started in background (minimized — listener.auto_start_window)")
        case "failed":
            pretty.warn(
                "could not auto-start watcher — run watcher manually or check .venv"
            )

    from telelink.startup_sync import run_shell_startup_sync

    run_shell_startup_sync(statey)

    while True:
        statey.maybe_render_header()
        try:
            line = prompts.shell_line(prompt=statey.prompt_path)
        except (EOFError, KeyboardInterrupt):
            from telelink.statey.types import NavAction

            result = statey.handle_interrupt()
            if result.action == NavAction.EXIT:
                _say(chalk.plain("\nlater."))
                break
            continue

        if line == BACK:
            statey.back()
            continue

        if line == HELP:
            statey.show_help()
            continue

        try:
            result = statey.handle(line)
        except Exception as exc:
            _say(chalk.muted(f"error: {exc}"))
            continue

        if not statey.dispatch(result):
            _say(chalk.plain("later."))
            break

    return 0
