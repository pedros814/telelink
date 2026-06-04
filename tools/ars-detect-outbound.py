#!/usr/bin/env python
"""Debug ARS outbound detector for a session.

Usage:
    python tools/ars-detect-outbound.py <session-name>
    python tools/ars-detect-outbound.py <session-name> --verbose
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    if len(sys.argv) < 2:
        print('usage: ars-detect-outbound.py <session-name> [--verbose]', file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    verbose = '--verbose' in sys.argv
    
    from telelink.config import load_config
    from telelink.ars_store import load_session
    from telelink.ars_detect import detect_outbound
    from telelink.session import get_session
    from telelink.convo import fetch_conversation
    from telelink.convo_parse import ConvoQuery
    
    config = load_config()
    session = load_session(config, name)
    tl = get_session()
    
    # Fetch thread
    contact = session.get('contact_resolved', {})
    target = contact.get('name') or contact.get('phone') or session.get('contact_query', '')
    limit = int(session.get('thread_limit') or config.get('ars', {}).get('thread_limit', 50))
    query = ConvoQuery(target=target, limit=limit)
    rows, display, phone, source = fetch_conversation(query, config=config, contact_store=tl.contact_store)
    
    result = detect_outbound(session, config, rows=rows, contact_store=tl.contact_store)
    
    output = {
        'matched': result.matched,
        'source': result.source,
        'session_state': session.get('state'),
        'thread_rows': len(rows),
        'thread_source': source,
    }
    if verbose and result.record:
        output['record'] = result.record
    if verbose:
        output['pending'] = session.get('pending')
        output['contact_resolved'] = session.get('contact_resolved')
    
    print(json.dumps(output, indent=2, default=str))
    sys.exit(0 if result.matched else 1)

if __name__ == '__main__':
    main()
