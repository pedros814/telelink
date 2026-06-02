"""Make JSON greppable — inspired by gron (https://github.com/tomnomnom/gron)."""

from __future__ import annotations

import json
import re
from typing import Any


def _quote_key(key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def gron(data: Any, *, root: str = "json") -> str:
    lines: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if not value:
                lines.append(f"{path} = {{}};")
                return
            for key, item in value.items():
                child = f"{path}.{_quote_key(str(key))}"
                walk(item, child)
            return
        if isinstance(value, list):
            if not value:
                lines.append(f"{path} = [];")
                return
            for idx, item in enumerate(value):
                walk(item, f"{path}[{idx}]")
            return
        lines.append(f"{path} = {_format_value(value)};")

    if isinstance(data, list):
        if not data:
            lines.append(f"{root} = [];")
        for idx, item in enumerate(data):
            if isinstance(item, (dict, list)):
                walk(item, f"{root}[{idx}]")
            else:
                lines.append(f"{root}[{idx}] = {_format_value(item)};")
    else:
        walk(data, root)
    return "\n".join(lines)


def gron_caught(rows: list[dict[str, Any]], *, root: str = "json") -> str:
    if not rows:
        return f"{root} = [];"
    return gron(rows, root=root)


gron_tasks = gron_caught
