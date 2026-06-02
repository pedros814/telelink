"""Verification helpers for UI automation."""

from telelink.ui_automation.verify.predicates import verify_send_delivered
from telelink.ui_automation.verify.runner import run_verify

__all__ = ["run_verify", "verify_send_delivered"]
