#!/usr/bin/env python3
"""Dry-run ARS state transitions with fixture JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telelink.ars_state import transition
from telelink.json_out import print_json


def _load_json(path: str | None) -> Any:
    if not path:
        return None
    with Path(path).open(encoding="utf-8-sig") as f:
        return json.load(f)


def _stdin_json() -> dict[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if isinstance(data, dict):
        return data
    raise ValueError("stdin JSON must be an object")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_state", default="", help="Override initial state")
    parser.add_argument("--event", required=True, help="Event name")
    parser.add_argument("--session", help="Session JSON fixture path")
    parser.add_argument("--stdin", action="store_true", help="Read session JSON from stdin")
    parser.add_argument("--ctx", default="", help="Inline JSON object for ctx")
    parser.add_argument("--ctx-file", help="JSON file for ctx")
    args = parser.parse_args()

    session = {}
    if args.session:
        loaded = _load_json(args.session)
        if isinstance(loaded, dict):
            session = loaded
    elif args.stdin:
        session = _stdin_json()
    else:
        session = {}

    if args.from_state:
        session["state"] = args.from_state

    ctx: dict[str, Any] = {}
    if args.ctx_file:
        loaded = _load_json(args.ctx_file)
        if isinstance(loaded, dict):
            ctx.update(loaded)
    if args.ctx:
        loaded = json.loads(args.ctx)
        if isinstance(loaded, dict):
            ctx.update(loaded)
        else:
            raise ValueError("--ctx must be a JSON object")

    next_session = transition(session, args.event, ctx=ctx)
    print_json(next_session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

