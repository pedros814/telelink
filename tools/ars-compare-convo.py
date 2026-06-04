#!/usr/bin/env python3
"""Same contact: fetch_conversation vs what ARS tick used - diff sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description="Compare convo sources for ARS.")
    parser.add_argument("contact", type=str, help="Contact query")
    args = parser.parse_args()

    print(f"Comparing convo for contact: {args.contact}...")
    print("Not fully implemented: Requires telelink.convo.fetch_conversation and ars session data.")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
