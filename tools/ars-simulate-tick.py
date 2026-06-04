#!/usr/bin/env python3
"""Run N ticks against live or --fixture-thread without window."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate ARS ticks.")
    parser.add_argument("session", type=str, help="Session name to run ticks for")
    parser.add_argument("--ticks", type=int, default=1, help="Number of ticks to simulate")
    parser.add_argument("--interval", type=float, default=0.0, help="Wait interval between ticks in seconds")
    parser.add_argument("--fixture-thread", type=str, help="Path to fixture JSON thread to use instead of live DB")
    args = parser.parse_args()

    print(f"Simulating {args.ticks} ticks for session '{args.session}'...")
    if args.fixture_thread:
        print(f"Using fixture thread: {args.fixture_thread}")
        
    for i in range(args.ticks):
        print(f"--- Tick {i+1} ---")
        # Stub implementation
        print("Tick executed (mock).")
        if i < args.ticks - 1 and args.interval > 0:
            time.sleep(args.interval)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
