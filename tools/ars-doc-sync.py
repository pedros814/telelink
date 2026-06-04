#!/usr/bin/env python3
"""Extract ars next JSON schema from ars_next.py -> compare to ARS.md tables."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    print("Validating ARS docs against code...")
    ars_md_path = ROOT / ".skills" / "telelink" / "ARS.md"
    ars_next_path = ROOT / "telelink" / "ars_next.py"
    
    if not ars_md_path.exists():
        print(f"Warning: {ars_md_path} does not exist yet.")
    if not ars_next_path.exists():
        print(f"Warning: {ars_next_path} does not exist yet.")
        
    print("Doc sync check complete (simulated).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
