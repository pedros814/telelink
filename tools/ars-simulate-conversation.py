#!/usr/bin/env python3
"""Append synthetic rows to a test session cursor (dev only; never production path)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description="Append synthetic rows to a test session.")
    parser.add_argument("session", type=str, help="Session to modify")
    parser.add_argument("--message", type=str, required=True, help="Message body")
    parser.add_argument("--direction", choices=["inbound", "outbound"], default="inbound")
    args = parser.parse_args()
    
    print(f"Appending {args.direction} row to test session '{args.session}' (Not fully implemented yet)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
