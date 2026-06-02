"""CLI config get / set / list — edits config.yaml on disk."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from telelink.config import DEFAULT_CONFIG_NAME

EXAMPLE_CONFIG_NAME = "config.example.yaml"

try:
    from ruamel.yaml import YAML as _RuamelYAML

    _ruamel = _RuamelYAML()
    _ruamel.preserve_quotes = True
    _ruamel.default_flow_style = False
    _ruamel.width = 4096
    _HAS_RUAMEL = True
except ImportError:
    _ruamel = None
    _HAS_RUAMEL = False
from telelink.messaging import _OWNER_TAG_GROUPS

# Friendly names → dotted path (owner tags + common shortcuts)
_STATIC_ALIASES: dict[str, str] = {
    "only_clients": "routing.only_contacts",
    "clients_only": "routing.only_contacts",
    "unmatched": "routing.unmatched_label",
    "caught": "output.caught_file",
    "tasks": "output.caught_file",
    "tasks_file": "output.caught_file",
    "data_dir": "output.dir",
    "output_dir": "output.dir",
    "port": "intake.port",
    "host": "intake.host",
    "token": "intake.token",
    "public_url": "intake.public_url",
    "tunnel": "intake.global_tunnel",
    "global_tunnel": "intake.global_tunnel",
    "github_token": "outtake.github.token",
    "github_owner": "outtake.github.owner",
    "github_repo": "outtake.github.repo",
    "outtake_ttl": "outtake.auto_delete",
    "outtake_auto_delete": "outtake.auto_delete",
    "outtake_poll": "outtake.auto_delete_poll",
    "airdrop_enabled": "airdrop.enabled",
    "convo_enabled": "convo.enabled",
    "airdrop_receiver": "airdrop.default_receiver",
    "airdrop_mode": "airdrop.mode",
    "airdrop_host": "airdrop.ssh.host",
    "outtake_transport": "outtake.transport",
    "poll": "listener.poll_seconds",
    "watcher_poll": "listener.poll_seconds",
    "watcher_auto": "listener.auto_start_window",
    "auto_watcher": "listener.auto_start_window",
    "auto_start_watcher": "listener.auto_start_window",
    "watcher_start_delay": "listener.auto_start_delay",
    "auto_start_delay": "listener.auto_start_delay",
    "console_nudge": "listener.console_nudge",
    "watcher_nudge": "listener.console_nudge",
    "console_nudge_interval": "listener.console_nudge_interval",
    "watcher_nudge_interval": "listener.console_nudge_interval",
    "ocr": "ocr.enabled",
    "harvest": "harvest.enabled",
    "messaging": "messaging.enabled",
    "intake": "intake.enabled",
    "debounce": "media.debounce_seconds",
    "ttl": "cache.ttl_seconds",
    "analyze_ttl": "analyze.ttl",
    "analyze_screenshot": "analyze.screenshot",
    "analyze": "analyze.screenshot",
    "method": "messaging.method",
    "sent_max": "messaging.sent_log_max_entries",
    "sent_log_max": "messaging.sent_log_max_entries",
    "import_tasks": "sync.import_caught_on_startup",
    "import_caught": "sync.import_caught_on_startup",
    "auto_sync": "sync.auto_sync",
    "sync_auto": "sync.auto_sync",
    "auto_sync_interval": "sync.auto_sync_interval",
    "sync_interval": "sync.auto_sync_interval",
    "calendar_enabled": "calendar.enabled",
    "calendar_poll": "calendar.poll_seconds",
    "calendar_remind": "calendar.remind_interval",
    "calls_enabled": "calls.enabled",
    "calls_ttl": "calls.ttl",
    "calls_remind": "calls.remind_interval",
    "calls_file": "calls.file",
    "google_calendar": "calendar.google.enabled",
    "google_credentials": "calendar.google.credentials_file",
    "google_calendar_id": "calendar.google.calendar_id",
}

for _cfg_key, _tags in _OWNER_TAG_GROUPS:
    _path = f"owner.{_cfg_key}"
    _STATIC_ALIASES[_cfg_key] = _path
    for _tag in _tags:
        _STATIC_ALIASES[_tag.lower()] = _path

_BOOL_TRUE = frozenset({"1", "true", "yes", "on", "enabled"})
_BOOL_FALSE = frozenset({"0", "false", "no", "off", "disabled"})


def config_path(path: Path | None = None) -> Path:
    return path or Path.cwd() / DEFAULT_CONFIG_NAME


def example_config_path(path: Path | None = None) -> Path:
    return config_path(path).parent / EXAMPLE_CONFIG_NAME


def config_reset(*, path: Path | None = None, example_path: Path | None = None) -> Path:
    """Replace config.yaml with config.example.yaml. Returns path to config.yaml."""
    dest = config_path(path)
    src = example_path or example_config_path(path)
    if not src.exists():
        raise FileNotFoundError(f"No {EXAMPLE_CONFIG_NAME} found next to {DEFAULT_CONFIG_NAME}.")
    shutil.copy2(src, dest)
    _reload_session()
    return dest


def load_raw_config(path: Path | None = None) -> dict[str, Any]:
    p = config_path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No {DEFAULT_CONFIG_NAME} found. Copy config.example.yaml to config.yaml."
        )
    with p.open(encoding="utf-8") as f:
        if _HAS_RUAMEL and _ruamel is not None:
            data = _ruamel.load(f)
            return data if isinstance(data, dict) else {}
        return yaml.safe_load(f) or {}


def save_raw_config(data: dict[str, Any], path: Path | None = None) -> Path:
    p = config_path(path)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        if _HAS_RUAMEL and _ruamel is not None:
            _ruamel.dump(data, f)
        else:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
    return p


def flatten_config(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            flat.update(flatten_config(value, path))
        else:
            flat[path] = value
    return flat


def _path_tuple(dotted: str) -> tuple[str, ...]:
    return tuple(p for p in dotted.replace("/", ".").split(".") if p)


def resolve_config_key(key: str, flat: dict[str, Any]) -> tuple[str, ...]:
    raw = (key or "").strip()
    if not raw:
        raise ValueError("config key is required")

    norm = raw.lower().replace("-", "_")
    dotted = norm.replace("_", ".")

    if norm in _STATIC_ALIASES:
        return _path_tuple(_STATIC_ALIASES[norm])

    if dotted in flat:
        return _path_tuple(dotted)

    if norm in flat:
        return _path_tuple(norm)

    # last segment match (e.g. "port" → intake.port if unique)
    matches = [
        p
        for p in flat
        if p == dotted or p.endswith("." + dotted) or p.split(".")[-1] == norm
    ]
    if len(matches) == 1:
        return _path_tuple(matches[0])
    if len(matches) > 1:
        hint = ", ".join(sorted(matches)[:8])
        extra = f" (+{len(matches) - 8} more)" if len(matches) > 8 else ""
        raise ValueError(f"ambiguous key {key!r} — use a full path, e.g. {hint}{extra}")

    # fuzzy: substring in path
    partial = [p for p in flat if norm in p.replace("_", "").lower()]
    if len(partial) == 1:
        return _path_tuple(partial[0])

    raise ValueError(
        f"unknown config key {key!r} — run: telelink config list"
    )


def get_by_path(data: dict[str, Any], parts: tuple[str, ...]) -> Any:
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(".".join(parts))
        cur = cur[part]
    return cur


def set_by_path(data: dict[str, Any], parts: tuple[str, ...], value: Any) -> Any:
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    old = cur.get(parts[-1])
    cur[parts[-1]] = value
    return old


def parse_config_value(text: str, *, current: Any = None) -> Any:
    s = text.strip()
    if not s and current is not None:
        return current

    low = s.lower()
    if low in ("null", "none", "~"):
        return None
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False

    if s.startswith(("[", "{")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

    if isinstance(current, list) and "," in s and not s.startswith("["):
        return [p.strip() for p in s.split(",") if p.strip()]

    if isinstance(current, int) and re.fullmatch(r"-?\d+", s):
        return int(s)
    if isinstance(current, float) and re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return float(s) if "." in s else int(s)

    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)

    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    return s


def format_config_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if all(isinstance(x, (str, int, float, bool)) or x is None for x in value):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    return str(value)


def _reload_session() -> None:
    try:
        from telelink.session import get_session, reset_session

        try:
            get_session().reload_config()
        except Exception:
            reset_session()
    except Exception:
        pass


def config_edit(
    key: str,
    value_parts: list[str],
    *,
    path: Path | None = None,
) -> tuple[str, Any, Any]:
    """Set a config value. Returns (dotted_path, old, new)."""
    if not value_parts:
        raise ValueError('value is required — e.g. config edit business "Your Business"')

    p = config_path(path)
    data = load_raw_config(p)
    flat = flatten_config(data)
    parts = resolve_config_key(key, flat)
    dotted = ".".join(parts)

    current = flat.get(dotted)
    raw_value = " ".join(value_parts)
    new_value = parse_config_value(raw_value, current=current)
    old_value = set_by_path(data, parts, new_value)
    save_raw_config(data, p)
    _reload_session()
    return dotted, old_value, new_value


def config_get(key: str, *, path: Path | None = None) -> tuple[str, Any]:
    data = load_raw_config(path)
    flat = flatten_config(data)
    parts = resolve_config_key(key, flat)
    dotted = ".".join(parts)
    return dotted, flat[dotted]


def config_list_keys(*, path: Path | None = None) -> list[tuple[str, Any]]:
    data = load_raw_config(path)
    return sorted(flatten_config(data).items(), key=lambda x: x[0].lower())


def suggest_keys(query: str, flat: dict[str, Any], *, limit: int = 6) -> list[str]:
    q = query.lower().replace("-", "_")
    scored: list[tuple[int, str]] = []
    for p in flat:
        pl = p.lower()
        if q in pl or q in pl.replace("_", ""):
            score = 0 if pl.endswith(q) or pl.split(".")[-1] == q else 1
            scored.append((score, p))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [p for _, p in scored[:limit]]
