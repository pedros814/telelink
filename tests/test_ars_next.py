"""Tests for ARS Phase 2 next JSON payload."""

import pytest
from pathlib import Path

from telelink.ars_next import build_next_json

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
def base_config():
    return {"ars": {}}

def test_reply_action(base_session, base_config):
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "reply"
    assert payload["needs_tending"] is True
    assert "tone" in payload["commands"]
    assert "thread" in payload["commands"]
    assert "inbound" in payload["commands"]
    assert "send" in payload["commands"]
    assert "ack" in payload["commands"]
    assert "agent_rules" in payload
    assert len(payload["agent_rules"]) > 0

def test_wait_action(base_session, base_config):
    base_session["state"] = "waiting"
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "wait"
    assert payload["needs_tending"] is False
    assert "poll" in payload["commands"]
    assert "status" in payload["commands"]

def test_stopped_action(base_session, base_config):
    base_session["state"] = "stopped"
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "stopped"

def test_error_action(base_session, base_config):
    base_session["state"] = "error"
    base_session["errors"] = [{"message": "something broke"}]
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "error"
    assert payload["error"] == "something broke"

def test_cooldown_action(base_session, base_config):
    base_session["state"] = "cooldown"
    base_session["cooldown_until"] = "2026-06-01T12:05:00Z"
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "wait"
    assert payload["cooldown_until"] == "2026-06-01T12:05:00Z"

def test_awaiting_agent_action(base_session, base_config):
    base_session["state"] = "awaiting_agent"
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "reply"
    assert payload["awaiting_send"] is True

def test_stale_agent_flag(base_session, base_config):
    base_session["stale_agent"] = True
    payload = build_next_json(base_session, base_config, repo_root=Path("."), run_path=".\\telelink.ps1")
    
    assert payload["action"] == "reply"
    assert payload["stale_agent"] is True
