"""One-shot agent guide and context — skip codebase exploration."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

from telelink.analyze_snapshot import analyze_dir, analyze_options
from telelink.session import get_session

_GUIDE_PATH = Path(__file__).resolve().parent.parent / "AGENTS.md"


def _repo_root() -> Path:
    return Path.cwd().resolve()


def _read_guide() -> str:
    if _GUIDE_PATH.is_file():
        return _GUIDE_PATH.read_text(encoding="utf-8")
    return (
        "TeleLink agent guide missing (AGENTS.md).\n"
        "Run: python -m telelink agent context\n"
    )


def _caught_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:10]:
        out.append(
            {
                "at": row.get("at") or row.get("timestamp"),
                "sender": row.get("sender") or row.get("from"),
                "contact": row.get("contact") or row.get("client"),
                "channel": row.get("channel") or row.get("platform"),
                "kind": row.get("message_kind") or row.get("kind"),
                "text": (row.get("text") or row.get("body") or row.get("message") or "")[:500],
            }
        )
    return out


def build_agent_context(*, caught_limit: int = 5) -> dict[str, Any]:
    root = _repo_root()
    session = get_session()
    config = session.config_fresh()
    owner = config.get("owner") or {}

    analyze_opts = analyze_options(config)
    analyze_meta: dict[str, Any] | None = None
    analyze_png: str | None = None
    if analyze_opts["enabled"]:
        json_path = analyze_dir(config) / "latest.json"
        png_path = analyze_dir(config) / "latest.png"
        if json_path.is_file():
            try:
                analyze_meta = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                analyze_meta = None
        if png_path.is_file():
            analyze_png = str(png_path.resolve())

    rows = session.caught_store.list_caught(limit=max(1, caught_limit))

    ps1 = root / "telelink.ps1"
    run = f".\\telelink.ps1" if ps1.is_file() else ".\\.venv\\Scripts\\python.exe -m telelink"

    return {
        "repo_root": str(root),
        "run": run,
        "owner": {
            "personal_name_short": owner.get("personal_name_short"),
            "business_name": owner.get("business_name"),
            "timezone": owner.get("timezone"),
            "talking_tone": owner.get("talking_tone"),
        },
        "recent_caught": _caught_summary(rows),
        "analyze": {
            "enabled": analyze_opts["enabled"],
            "latest_json": analyze_meta,
            "latest_png": analyze_png,
            "ttl_seconds": analyze_opts["ttl_seconds"],
        },
        "commands": {
            "agent_context": f"{run} agent context",
            "what_did_contact_send": f'{run} received {{who}}',
            "what_did_contact_send_last_n": f"{run} received last {{n}} {{who}}",
            "read_sms_thread": f'{run} convo "{{who}}" --raw',
            "read_notifications": f"{run} caught --raw --limit 10",
            "send_now": f'{run} send "{{who}}" {{message}}',
            "send_later": f'{run} send in%{{when}}% "{{who}}" {{message}}',
            "contacts": f"{run} contacts",
            "missed_calls": f"{run} missed",
        },
        "hint": (
            "What did X send me? → received mom (JSON, full bodies). "
            "Do not use convo alone for that. Read AGENTS.md first."
        ),
    }


def cmd_agent(args: Namespace) -> int:
    action = getattr(args, "agent_action", None) or "guide"
    if action == "context":
        from telelink.json_out import print_json

        limit = getattr(args, "limit", None) or 5
        print_json(build_agent_context(caught_limit=int(limit)))
        return 0
    print(_read_guide())
    return 0
