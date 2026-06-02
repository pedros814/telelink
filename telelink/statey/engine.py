"""Statey — stack-based terminal state management."""

from __future__ import annotations

from typing import Any

from telelink import chalk
from telelink.statey.types import FlowStep, HandleResult, NavAction, Screen
from telelink.statey import ui


class Statey:
    NAV_BACK = frozenset({"back", "b", "..", "up"})
    NAV_HOME = frozenset({"home", "menu", "top", "root"})
    NAV_CANCEL = frozenset({"cancel", "c", "abort"})
    NAV_STOP = frozenset({"stop"})
    NAV_EXIT = frozenset({"exit", "quit", "q"})
    NAV_HELP = frozenset({"help", "?"})

    def __init__(self) -> None:
        self.screens: dict[str, Screen] = {}
        self.stack: list[str] = ["root"]
        self.flow_name: str | None = None
        self.flow_steps: list[FlowStep] = []
        self.flow_index: int = 0
        self.flow_data: dict[str, Any] = {}
        self._config: dict | None = None
        self._store: Any = None
        self._header_pending = False
        self.mode: str = "idle"

    def register(self, screen: Screen) -> None:
        self.screens[screen.id] = screen

    @property
    def current_id(self) -> str:
        return self.stack[-1]

    @property
    def current(self) -> Screen:
        return self.screens[self.current_id]

    @property
    def at_root(self) -> bool:
        return len(self.stack) == 1

    @property
    def in_flow(self) -> bool:
        return self.flow_name is not None

    @property
    def prompt_path(self) -> str:
        parts = ["telelink"]
        for sid in self.stack[1:]:
            parts.append(self.screens[sid].title)
        if self.flow_name:
            parts.append(self.flow_name)
        return " › ".join(parts)

    def config(self) -> dict:
        from telelink.session import get_session

        return get_session().config_fresh()

    def store(self):
        from telelink.session import get_session

        return get_session().task_store

    def contact_store(self):
        from telelink.session import get_session

        return get_session().contact_store

    def reload_session(self) -> None:
        from telelink.session import reset_session

        reset_session()
        self._config = None
        self._store = None

    def start_flow(self, name: str, steps: list[FlowStep], *, data: dict[str, Any] | None = None) -> None:
        self.flow_name = name
        self.flow_steps = steps
        self.flow_index = 0
        self.flow_data = dict(data or {})
        self._header_pending = True

    def cancel_flow(self) -> None:
        self.flow_name = None
        self.flow_steps = []
        self.flow_index = 0
        self.flow_data = {}
        self._header_pending = True

    def push(self, screen_id: str) -> None:
        if screen_id not in self.screens:
            raise KeyError(screen_id)
        self.cancel_flow()
        self.stack.append(screen_id)
        self._header_pending = True
        on_enter = self.screens[screen_id].on_enter
        if on_enter:
            on_enter(self)

    def back(self) -> bool:
        if self.in_flow:
            self.cancel_flow()
            return True
        if len(self.stack) > 1:
            self.stack.pop()
            self._header_pending = True
            return True
        return False

    def home(self) -> None:
        self.stack = ["root"]
        self.cancel_flow()
        self.mode = "idle"
        self._header_pending = True

    def maybe_render_header(self) -> None:
        if not self._header_pending:
            return
        if self.at_root and not self.in_flow:
            self._header_pending = False
            return
        ui.screen_header(self)
        self._header_pending = False

    def show_help(self) -> None:
        ui.help_body(self)

    def show_flow_prompt(self) -> None:
        if not self.in_flow:
            return
        step = self.flow_steps[self.flow_index]
        print(flush=True)
        if step.kind == "select":
            items = [(str(i + 1), choice) for i, choice in enumerate(step.choices)]
            ui.menu(step.message, items)
            print(chalk.muted("  enter a number"), flush=True)
        elif step.kind == "confirm":
            suffix = chalk.muted("Y/n" if step.initial else "y/N")
            print(f"{chalk.baby('?')} {step.message} {suffix}", flush=True)
        else:
            hint = chalk.muted(f"({step.initial})") if step.initial else ""
            print(f"{chalk.baby('?')} {step.message} {hint}".strip(), flush=True)

    def _handle_flow_step(self, line: str) -> HandleResult:
        from telelink import chalk

        step = self.flow_steps[self.flow_index]
        value = line.strip()

        if step.kind == "confirm":
            if not value:
                answer = bool(step.initial)
            else:
                answer = value.lower() in ("y", "yes", "1", "true")
        elif step.kind == "select":
            if value.isdigit():
                idx = int(value) - 1
                answer = step.choices[idx] if 0 <= idx < len(step.choices) else step.choices[0]
            elif value in step.choices:
                answer = value
            else:
                pretty_msg = chalk.muted("pick a number from the menu")
                print(pretty_msg, flush=True)
                self.show_flow_prompt()
                return HandleResult()
        else:
            answer = value or step.initial or ""

        self.flow_data[step.name] = answer
        self.flow_index += 1

        if self.flow_index >= len(self.flow_steps):
            name = self.flow_name or ""
            data = dict(self.flow_data)
            self.cancel_flow()
            return self._complete_flow(name, data)

        self.show_flow_prompt()
        return HandleResult()

    def _complete_flow(self, name: str, data: dict[str, Any]) -> HandleResult:
        handler = self._flow_handlers.get(name)
        if handler:
            handler(self, data)
        return HandleResult()

    _flow_handlers: dict[str, Any] = {}

    @classmethod
    def on_flow(cls, name: str):
        def deco(fn):
            cls._flow_handlers[name] = fn
            return fn

        return deco

    def handle_interrupt(self) -> HandleResult:
        if self.in_flow:
            self.cancel_flow()
            return HandleResult()
        if not self.at_root:
            self.back()
            return HandleResult()
        return HandleResult(NavAction.EXIT)

    def handle(self, line: str) -> HandleResult:
        parts = line.split()
        cmd = parts[0].lower() if parts else ""
        rest = parts[1:]
        raw = line.strip().lower()
        if not raw:
            return HandleResult()

        if cmd in ("help", "?", "how") and rest:
            from telelink.how_guide import display_help_topic

            display_help_topic(rest)
            return HandleResult()

        if raw in self.NAV_EXIT:
            if self.at_root and not self.in_flow:
                return HandleResult(NavAction.EXIT)
            self.home()
            return HandleResult()

        if cmd in self.NAV_BACK:
            self.back()
            return HandleResult()

        if raw in self.NAV_HOME:
            if not self.at_root or self.in_flow:
                self.home()
            return HandleResult()

        if raw in self.NAV_CANCEL or raw in self.NAV_STOP:
            if self.in_flow or not self.at_root:
                if self.in_flow:
                    self.cancel_flow()
                else:
                    self.home()
                return HandleResult()
            return HandleResult()

        if raw in self.NAV_HELP:
            self.show_help()
            return HandleResult()

        if self.in_flow:
            return self._handle_flow_step(line)

        result = self.current.handle(self, line)
        return result or HandleResult()

    def dispatch(self, result: HandleResult) -> bool:
        if result.action == NavAction.EXIT:
            return False
        if result.action == NavAction.PUSH and result.target:
            self.push(result.target)
        elif result.action == NavAction.BACK:
            self.back()
        elif result.action == NavAction.HOME:
            self.home()
        return True
