"""Engine interface for Phone Link UI automation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from telelink.ui_automation.session import UiAutomationSession


@runtime_checkable
class UiEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def find_phone_link_window(self, session: UiAutomationSession | None = None) -> Any | None: ...

    def click_send(self, win: Any, body: str) -> bool: ...

    def unfocus_compose(self, win: Any) -> bool: ...

    def minimize_window(self, win: Any) -> bool: ...
