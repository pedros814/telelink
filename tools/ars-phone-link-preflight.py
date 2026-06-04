#!/usr/bin/env python3
"""Preflight: phone.db, messaging.method, sent_log, contacts resolve."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description="ARS Phone Link Preflight")
    parser.add_argument("contact", type=str, nargs="?", help="Optional contact to resolve")
    args = parser.parse_args()

    print("--- ARS Phone Link Preflight ---")
    
    # sent_log
    sent_log_path = ROOT / "data" / "sent.jsonl"
    print(f"sent_log exists: {'YES' if sent_log_path.exists() else 'NO'}")
    
    print("Not fully implemented: Requires telelink.config, telelink.contacts, etc.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
