#!/usr/bin/env python
"""Print ars next --raw JSON for a session without running the window.

Usage:
    python tools/ars-print-next.py <session-name>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    if len(sys.argv) < 2:
        print('usage: ars-print-next.py <session-name>', file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    from telelink.config import load_config
    from telelink.ars_store import load_session
    from telelink.ars_next import build_next_json
    
    config = load_config()
    session = load_session(config, name)
    payload = build_next_json(session, config, repo_root=ROOT, run_path='.\\telelink.ps1')
    print(json.dumps(payload, indent=2, default=str))

if __name__ == '__main__':
    main()
