#!/usr/bin/env python3
"""Pretty table: session, contact, state, pid alive, last tick."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    print(f"{'SESSION':<20} {'CONTACT':<15} {'STATE':<15} {'PID ALIVE':<10} {'LAST TICK'}")
    print("-" * 75)
    print("Not fully implemented: Requires telelink.ars_store.list_sessions()")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
