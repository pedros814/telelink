#!/usr/bin/env python3
"""Evaluate ARS needs_tending result from fixture rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telelink.ars_logic import needs_tending
from telelink.json_out import print_json


def _load_json(path: str | None) -> Any:
    if not path:
        return None
    p = Path(path)
    with p.open(encoding="utf-8-sig") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="Path to thread-*.json fixture")
    parser.add_argument("--session", help="Optional ARS session JSON")
    parser.add_argument("--config", help="Optional JSON object with ars config")
    parser.add_argument("--force", action="store_true", help="Ignore stale-hours check")
    args = parser.parse_args()

    rows = _load_json(args.fixture)
    if not isinstance(rows, list):
        raise SystemExit("fixture must be a JSON array of thread rows")
    session = _load_json(args.session) if args.session else None
    config = _load_json(args.config) if args.config else None

    result = needs_tending(rows, session=session, config=config, force=args.force)
    payload = result.to_dict()
    payload["fixture"] = str(args.fixture)
    print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

