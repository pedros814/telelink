"""Session storage helpers for ARS."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telelink.duration import parse_duration

_SESSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", flags=re.IGNORECASE)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_session_slug(session: str) -> str:
    raw = str(session or "").strip()
    if not raw:
        raise ValueError("session name is required")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError("invalid session name: path separators are not allowed")
    slug = raw.lower()
    if not _SESSION_RE.fullmatch(slug):
        raise ValueError("invalid session name: use [a-z0-9][a-z0-9_-]{0,63}")
    return slug


def ars_dir(config: dict[str, Any]) -> Path:
    out = config.get("output") or {}
    ars_cfg = config.get("ars") or {}
    out_dir = Path(out.get("dir", "./data"))
    custom = str(ars_cfg.get("dir") or "").strip()
    if custom:
        base = Path(custom)
        if not base.is_absolute():
            base = out_dir / base
    else:
        base = out_dir / "ars"
    base.mkdir(parents=True, exist_ok=True)
    return base


def session_path(config: dict[str, Any], session: str) -> Path:
    slug = validate_session_slug(session)
    return ars_dir(config) / f"{slug}.json"


def pid_path(config: dict[str, Any], session: str) -> Path:
    slug = validate_session_slug(session)
    return ars_dir(config) / f"{slug}.pid"


def load_session(config: dict[str, Any] | str, session: str | dict[str, Any]) -> dict[str, Any]:
    """Load ARS session JSON. Accepts either (config, session) or (session, config)."""
    if isinstance(config, dict):
        cfg = config
        sess = str(session)
    else:
        cfg = dict(session) if isinstance(session, dict) else {}
        sess = str(config)
    if not cfg:
        raise ValueError("config is required")
    path = session_path(cfg, sess)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid ARS session payload: {path}")
    data["session"] = validate_session_slug(str(data.get("session") or sess))
    return data


def save_session(
    config: dict[str, Any] | dict[str, Any],
    payload: dict[str, Any] | dict[str, Any],
) -> dict[str, Any]:
    """Save ARS session. Accepts either (config, payload) or (payload, config)."""
    if isinstance(config, dict) and "output" in config:
        cfg = config
        body = dict(payload)
    else:
        cfg = dict(payload)
        body = dict(config)
    if not cfg:
        raise ValueError("config is required")
    if not isinstance(body, dict):
        raise TypeError("payload must be a dict")
    slug = validate_session_slug(str(body.get("session") or ""))
    path = session_path(cfg, slug)
    body["session"] = slug
    body["updated_at"] = str(body.get("updated_at") or _utc_now_iso())
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return body


def normalize_session_name(session: str) -> str:
    return validate_session_slug(session)


def create_session(
    session: str,
    *,
    contact_query: str,
    config: dict[str, Any],
    contact_store: Any | None = None,
    max_turns: int | None = None,
    start_idle: bool = False,
    no_bootstrap_reply: bool = False,
) -> dict[str, Any]:
    resolved = {"name": contact_query, "phone": contact_query}
    if contact_store is not None:
        try:
            got = contact_store.resolve(contact_query)
            resolved = {
                "name": str(got.get("name") or contact_query),
                "phone": str(got.get("phone") or contact_query),
            }
        except Exception:
            pass
    payload = new_session(
        session,
        contact_query,
        resolved,
        config=config,
        max_turns=max_turns,
        start_idle=start_idle,
        no_bootstrap_reply=no_bootstrap_reply,
    )
    return save_session(config, payload)


def read_pid(session: str, config: dict[str, Any]) -> int | None:
    path = pid_path(config, session)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(session: str, config: dict[str, Any], pid: int) -> None:
    pid_path(config, session).write_text(str(int(pid)), encoding="utf-8")


def clear_pid(session: str, config: dict[str, Any]) -> None:
    path = pid_path(config, session)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def delete_session(session: str, config: dict[str, Any]) -> bool:
    path = session_path(config, session)
    if not path.exists():
        return False
    path.unlink()
    return True


def load_session_legacy(config: dict[str, Any], session: str) -> dict[str, Any]:
    """Backward-compat alias with explicit argument names."""
    path = session_path(config, session)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid ARS session payload: {path}")
    data["session"] = validate_session_slug(str(data.get("session") or session))
    return data


def list_sessions(config: dict[str, Any]) -> list[dict[str, Any]]:
    base = ars_dir(config)
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            data["session"] = validate_session_slug(str(data.get("session") or path.stem))
            out.append(data)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    out.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return out


def new_session(
    session: str,
    contact_query: str,
    contact_resolved: dict[str, Any] | None,
    *,
    config: dict[str, Any] | None = None,
    max_turns: int | None = None,
    start_idle: bool = False,
    no_bootstrap_reply: bool = False,
) -> dict[str, Any]:
    slug = validate_session_slug(session)
    cfg = config or {}
    ars_cfg = cfg.get("ars") or {}
    poll_seconds = parse_duration(ars_cfg.get("poll_interval", "45s")) or 45
    cooldown_seconds = parse_duration(ars_cfg.get("cooldown", "30s")) or 30
    now = _utc_now_iso()
    return {
        "version": 1,
        "session": slug,
        "contact_query": str(contact_query or "").strip(),
        "contact_resolved": dict(contact_resolved or {}),
        "state": "paused" if start_idle else "starting",
        "created_at": now,
        "updated_at": now,
        "poll_interval_seconds": int(poll_seconds),
        "cooldown_seconds": int(cooldown_seconds),
        "turn_count": 0,
        "max_turns": max_turns if max_turns is not None else ars_cfg.get("max_turns"),
        "start_idle": start_idle,
        "no_bootstrap_reply": no_bootstrap_reply,
        "thread_cursor": {
            "last_inbound_id": "",
            "last_inbound_at": "",
            "last_inbound_body_hash": "",
            "last_outbound_at": "",
            "last_outbound_body_hash": "",
        },
        "pending": {},
        "last_action": {},
        "errors": [],
    }
