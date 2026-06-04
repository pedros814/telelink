"""Deferred startup sync — run ``sync`` in the shell after watcher auto-start."""

from __future__ import annotations

import os
import sys
from argparse import Namespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telelink.statey.engine import Statey


def should_defer_startup_sync(config: dict) -> bool:
    """Skip bootstrap sync in the interactive shell when watcher auto-starts first."""
    if os.environ.get("TELELINK_WATCHER") == "1":
        return False
    if os.environ.get("TELELINK_ARS") == "1":
        return False
    sync = config.get("sync") or {}
    if sync.get("on_startup", True) is False:
        return False
    from telelink.config import watcher_auto_start_enabled

    return watcher_auto_start_enabled(config)


def echo_shell_command(statey: Statey, command: str) -> None:
    """Print a shell line as if the user typed it (prompt + command)."""
    from telelink import chalk
    from telelink.statey.ui import render_prompt_path

    render_prompt_path(statey.prompt_path)
    sys.stdout.write(f"{chalk.plain(command)}\n")
    sys.stdout.flush()


def run_shell_startup_sync(statey: Statey) -> None:
    """After watcher handoff, run startup sync through the same path as typing ``sync``."""
    from telelink.config import load_config

    config = load_config()
    if not should_defer_startup_sync(config):
        return

    echo_shell_command(statey, "sync")
    statey.handle("sync")
