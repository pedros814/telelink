"""Stealth UI config helpers."""

from __future__ import annotations

from telelink.ui_stealth import stealth_ui_enabled, ui_navigate_enabled


def test_stealth_ui_defaults_on() -> None:
    assert stealth_ui_enabled({}) is True
    assert stealth_ui_enabled({"automation": {"stealth_ui": True}}) is True


def test_stealth_ui_can_disable() -> None:
    assert stealth_ui_enabled({"automation": {"stealth_ui": False}}) is False
    assert stealth_ui_enabled({"convo": {"stealth_ui": False}}) is False


def test_ui_navigate_ars_default_on() -> None:
    assert ui_navigate_enabled({}, for_ars=True) is True


def test_ui_navigate_ars_can_disable() -> None:
    assert ui_navigate_enabled({"ars": {"ui_navigate": False}}, for_ars=True) is False


def test_ui_navigate_convo_default_on() -> None:
    assert ui_navigate_enabled({}) is True


def test_ui_navigate_ars_override() -> None:
    cfg = {"ars": {"ui_navigate": True}}
    assert ui_navigate_enabled(cfg, for_ars=True) is True
