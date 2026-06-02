"""Shared Phone Link UI locator constants."""

from __future__ import annotations

# Legacy substring keys — do not use for top-level window find (see session.phone_link_title_match).
PHONE_LINK_TITLE_KEYS = ("phone link", "your phone")

COMPOSE_CONTROL_TYPES = ("Edit", "Document")

FAILURE_PATTERNS = (
    "not delivered",
    "failed to send",
    "message failed",
    "couldn't be sent",
    "could not be sent",
    "try again",
    "not sent",
    "send failed",
)

SEND_BUTTON_SPECS: tuple[dict[str, str], ...] = (
    {"title_re": r"(?i)^send$", "control_type": "Button"},
    {"title_re": r"(?i)send", "control_type": "Button"},
    {"auto_id_re": r"(?i).*send.*", "control_type": "Button"},
)

MINIMIZE_BUTTON_SPECS: tuple[dict[str, str], ...] = (
    {"title_re": r"(?i)^minimize$", "control_type": "Button"},
    {"title": "Minimize", "control_type": "Button"},
    {"auto_id_re": r"(?i).*minimize.*", "control_type": "Button"},
)

TITLE_BAR_SPECS: tuple[dict[str, str], ...] = (
    {"control_type": "TitleBar"},
    {"class_name": "TitleBar"},
)
