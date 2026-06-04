"""Tests for ARS Phase 2 outbound detection."""

import pytest
from datetime import datetime, timezone, timedelta

from telelink.ars_detect import detect_outbound, OutboundDetectResult

@pytest.fixture
def base_session():
    return {
        "session": "test-ars",
        "state": "need_reply",
        "contact_query": "Test",
        "contact_resolved": {"name": "Test", "phone": "+15551234567"},
        "pending": {"at": "2026-06-01T12:00:00Z", "body_preview": "Hello"},
        "updated_at": "2026-06-01T12:00:00Z",
    }

@pytest.fixture
def base_config(tmp_path):
    return {
        "ars": {
            "detect_send_via_sent_log": True,
            "detect_send_via_convo": True,
            "sent_match_window": "1000d",
            "assume_clicked_is_sent": False,
        },
        "output": {"dir": str(tmp_path)},
        "messaging": {"sent_log": str(tmp_path / "sent.jsonl")},
    }

def test_detect_stub_states(base_session, base_config):
    base_session["state"] = "waiting"
    result = detect_outbound(base_session, base_config)
    assert not result.matched

    base_session["state"] = "cooldown"
    result = detect_outbound(base_session, base_config)
    assert not result.matched

def test_detect_via_sent_log_match(base_session, base_config, tmp_path):
    sent_log = tmp_path / "sent.jsonl"
    record = '{"to_phone": "+15551234567", "timestamp": "2026-06-01T12:05:00Z", "auto_sent": true, "body": "test"}\n'
    sent_log.write_text(record)
    
    result = detect_outbound(base_session, base_config)
    assert result.matched
    assert result.source == "sent_log"

def test_detect_via_sent_log_no_match(base_session, base_config, tmp_path):
    sent_log = tmp_path / "sent.jsonl"
    # Different phone number
    record = '{"to_phone": "+19999999999", "timestamp": "2026-06-01T12:05:00Z", "auto_sent": true, "body": "test"}\n'
    sent_log.write_text(record)
    
    result = detect_outbound(base_session, base_config)
    assert not result.matched

def test_detect_via_sent_log_before_pending(base_session, base_config, tmp_path):
    sent_log = tmp_path / "sent.jsonl"
    # Timestamp is before pending (12:00:00Z)
    record = '{"to_phone": "+15551234567", "timestamp": "2026-06-01T11:55:00Z", "auto_sent": true, "body": "test"}\n'
    sent_log.write_text(record)
    
    result = detect_outbound(base_session, base_config)
    assert not result.matched

def test_detect_via_convo_match(base_session, base_config):
    base_session["state"] = "awaiting_agent"
    rows = [
        {"direction": "in", "timestamp": "2026-06-01T11:50:00Z", "body": "first"},
        {"direction": "in", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"}, # pending inbound
        {"direction": "out", "timestamp": "2026-06-01T12:10:00Z", "body": "reply"} # outbound after pending
    ]
    
    result = detect_outbound(base_session, base_config, rows=rows)
    assert result.matched
    assert result.source == "phone_db"
    assert result.record["body"] == "reply"

def test_detect_via_convo_no_outbound(base_session, base_config):
    rows = [
        {"direction": "in", "timestamp": "2026-06-01T11:50:00Z", "body": "first"},
        {"direction": "in", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"},
    ]
    
    result = detect_outbound(base_session, base_config, rows=rows)
    assert not result.matched

def test_detect_force_ack(base_session, base_config):
    ctx = {"force_ack": True}
    result = detect_outbound(base_session, base_config, ctx=ctx)
    assert result.matched
    assert result.source == "agent_force"

def test_detect_config_disable_sent_log(base_session, base_config, tmp_path):
    base_config["ars"]["detect_send_via_sent_log"] = False
    
    sent_log = tmp_path / "sent.jsonl"
    record = '{"to_phone": "+15551234567", "timestamp": "2026-06-01T12:05:00Z", "auto_sent": true, "body": "test"}\n'
    sent_log.write_text(record)
    
    result = detect_outbound(base_session, base_config)
    assert not result.matched

def test_detect_config_disable_convo(base_session, base_config):
    base_config["ars"]["detect_send_via_convo"] = False
    
    rows = [
        {"direction": "in", "timestamp": "2026-06-01T12:00:00Z", "body": "Hello"},
        {"direction": "out", "timestamp": "2026-06-01T12:10:00Z", "body": "reply"}
    ]
    
    result = detect_outbound(base_session, base_config, rows=rows)
    assert not result.matched
