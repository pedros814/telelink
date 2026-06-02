"""Statey types — screens, flows, navigation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from telelink.statey.engine import Statey


class NavAction(Enum):
    STAY = "stay"
    BACK = "back"
    HOME = "home"
    EXIT = "exit"
    PUSH = "push"


@dataclass
class HandleResult:
    action: NavAction = NavAction.STAY
    target: str | None = None


@dataclass
class FlowStep:
    name: str
    message: str
    kind: str = "text"
    choices: list[str] = field(default_factory=list)
    initial: Any = None


@dataclass
class Screen:
    id: str
    title: str
    handle: Callable[[Statey, str], HandleResult | None]
    on_enter: Callable[[Statey], None] | None = None
    help_lines: list[str] = field(default_factory=list)
