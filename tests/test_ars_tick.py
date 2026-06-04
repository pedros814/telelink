"""Tests for ARS Phase 2 tick pipeline."""

import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from telelink.ars_store import save_session, load_session

@pytest.fixture
def mock_fetch():
    with patch("telelink.ars_tick.fetch_conversation") as m:
        yield m

@pytest.fixture
def base_config(tmp_path):
    ars_dir = tmp_path / "data" / "ars"
    ars_dir.mkdir(parents=True)
    return {
        "ars": {
            "burst_coalesce_seconds": "0s",
            "sent_match_window": "1000d"
        },
        "output": {"dir": str(tmp_path / "data")},
        "messaging": {"sent_log": str(tmp_path / "data" / "sent.jsonl")},
    }

def test_tick_bootstrap_needs_reply(mock_fetch, base_config):
    from telelink.ars_tick import run_ars_tick
    
    session = {
        "session": "test-ars",
        "state": "starting",
        "contact_query": "Test"
    }
    save_session(base_config, session)
    
    mock_fetch.return_value = (
        [{"direction": "in", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"}],
        "Test Display",
        "+15551234567",
        "phone_db"
    )
    
    result = run_ars_tick("test-ars", base_config, contact_store=None)
    
    assert result.session["state"] == "need_reply"
    assert result.session["pending"]["body_preview"] == "Hello"

def test_tick_bootstrap_no_reply(mock_fetch, base_config):
    from telelink.ars_tick import run_ars_tick
    
    session = {
        "session": "test-ars",
        "state": "starting",
        "contact_query": "Test"
    }
    save_session(base_config, session)
    
    mock_fetch.return_value = (
        [{"direction": "out", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"}],
        "Test Display",
        "+15551234567",
        "phone_db"
    )
    
    result = run_ars_tick("test-ars", base_config, contact_store=None)
    
    assert result.session["state"] == "waiting"

def test_tick_waiting_new_inbound(mock_fetch, base_config):
    from telelink.ars_tick import run_ars_tick
    
    session = {
        "session": "test-ars",
        "state": "waiting",
        "contact_query": "Test",
        "contact_resolved": {"name": "Test", "phone": "+15551234567"}
    }
    save_session(base_config, session)
    
    mock_fetch.return_value = (
        [{"direction": "in", "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "body": "New message"}],
        "Test Display",
        "+15551234567",
        "phone_db"
    )
    
    result = run_ars_tick("test-ars", base_config, contact_store=None)
    
    assert result.session["state"] == "need_reply"
    assert result.session["pending"]["body_preview"] == "New message"

def test_tick_outbound_detected(mock_fetch, base_config, tmp_path):
    from telelink.ars_tick import run_ars_tick
    
    session = {
        "session": "test-ars",
        "state": "need_reply",
        "contact_query": "Test",
        "contact_resolved": {"name": "Test", "phone": "+15551234567"},
        "pending": {"at": "2026-06-01T12:00:00Z", "body_preview": "Hello"},
    }
    save_session(base_config, session)
    
    mock_fetch.return_value = (
        [{"direction": "in", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"}],
        "Test Display",
        "+15551234567",
        "phone_db"
    )
    
    sent_log = tmp_path / "data" / "sent.jsonl"
    record = '{"to_phone": "+15551234567", "timestamp": "2026-06-01T12:05:00Z", "auto_sent": true, "body": "test"}\n'
    sent_log.write_text(record)
    
    result = run_ars_tick("test-ars", base_config, contact_store=None)
    
    assert result.session["state"] == "cooldown"
