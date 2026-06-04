#!/usr/bin/env python
"""Dump ARS session state + derived needs_tending + action.

Usage:
    python tools/ars-dump-session.py <session-name>
    python tools/ars-dump-session.py <session-name> --simulate-tick
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    if len(sys.argv) < 2:
        print('usage: ars-dump-session.py <session-name> [--simulate-tick]', file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    simulate = '--simulate-tick' in sys.argv
    
    from telelink.config import load_config
    from telelink.ars_store import load_session
    from telelink.ars_next import build_next_json
    
    config = load_config()
    session = load_session(config, name)
    payload = build_next_json(session, config, repo_root=ROOT, run_path='.\\telelink.ps1')
    
    print(json.dumps({
        'session': session,
        'derived': payload,
    }, indent=2, default=str))
    
    if simulate:
        from telelink.ars_tick import run_ars_tick
        from telelink.session import get_session
        tl = get_session()
        result = run_ars_tick(name, config=config, contact_store=tl.contact_store)
        after = build_next_json(result.session, config, repo_root=ROOT, run_path='.\\telelink.ps1')
        print('\n--- after tick ---')
        print(json.dumps(after, indent=2, default=str))

if __name__ == '__main__':
    main()
