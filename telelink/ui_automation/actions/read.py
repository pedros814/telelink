"""Conversation read/scrape actions for Phone Link UI automation."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

try:
    from telelink.ui_automation.config_helpers import get_automation_config
    from telelink.ui_automation.engines.pywinauto_engine import PywinautoEngine
    from telelink.ui_automation.orchestrator import run_action
except Exception:  # pragma: no cover - standalone fallback path
    get_automation_config = None  # type: ignore[assignment]
    PywinautoEngine = None  # type: ignore[assignment]
    run_action = None  # type: ignore[assignment]

_SKIP_BODIES = frozenset(
    {
        "messages",
        "conversations",
        "recent",
        "emoji",
        "send",
        "new message",
        "phone link",
    }
)
_UI_TS_RE = re.compile(
    r"(\w{3,9})\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def elements_by_automation_id(win, automation_id: str, *, control_type: str | None = None):
    out = []
    nodes = win.descendants(control_type=control_type) if control_type else win.descendants()
    for el in nodes:
        try:
            aid = getattr(el.element_info, "automation_id", None) or ""
            if aid == automation_id:
                out.append(el)
        except Exception:
            continue
    return out


def parse_ui_timestamp(raw: str) -> str:
    match = _UI_TS_RE.search(raw or "")
    if not match:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    mon_str, day, year, hour, minute, ampm = match.groups()
    month = _MONTHS.get(mon_str[:3].lower(), 1)
    h = int(hour)
    if ampm.upper() == "PM" and h != 12:
        h += 12
    if ampm.upper() == "AM" and h == 12:
        h = 0
    try:
        dt = datetime(int(year), month, int(day), h, int(minute), tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def direction_from_item(item_text: str, sender: str, peer_name: str) -> str:
    low = (item_text or "").lower()
    if "message you sent" in low or low.startswith("you sent"):
        return "out"
    sender_low = (sender or "").lower()
    if sender_low in ("you", "me"):
        return "out"
    if peer_name and peer_name.lower() in sender_low:
        return "in"
    if "message from" in low:
        return "in"
    return "in"


def extract_messages(win, *, peer_name: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    bodies = elements_by_automation_id(win, "MessageBody", control_type="Text")
    if not bodies:
        bodies = elements_by_automation_id(win, "MessageBody")
    for body_el in bodies:
        try:
            body = (body_el.window_text() or "").strip()
        except Exception:
            continue
        if not body or body.lower() in _SKIP_BODIES:
            continue

        sender = peer_name
        item_text = ""
        try:
            parent = body_el
            for _ in range(6):
                parent = parent.parent()
                control_type = getattr(parent.element_info, "control_type", "") or ""
                if control_type == "ListItem":
                    item_text = parent.window_text() or ""
                    break
        except Exception:
            pass

        try:
            senders = elements_by_automation_id(body_el.parent(), "MessageSender", control_type="Text")
            if not senders:
                senders = elements_by_automation_id(body_el.parent(), "MessageSender")
            for el in senders:
                sender = (el.window_text() or sender).strip() or sender
                break
        except Exception:
            pass

        key = (body, sender)
        if key in seen:
            continue
        seen.add(key)

        direction = direction_from_item(item_text, sender, peer_name)
        rows.append(
            {
                "id": f"plink-ui-{len(rows)}",
                "direction": direction,
                "body": body,
                "from_address": sender if direction == "in" else "you",
                "to_address": "you" if direction == "in" else sender,
                "peer": peer_name,
                "peer_name": peer_name,
                "timestamp": parse_ui_timestamp(item_text),
                "source": "phone_link_ui",
            }
        )

    rows.sort(key=lambda r: r.get("timestamp") or "")
    if limit and len(rows) > limit:
        return rows[-limit:]
    return rows


def read_messages_orchestrated(
    win,
    *,
    peer_name: str,
    limit: int,
    engine: str = "pywinauto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if win is None:
        return {
            "ok": False,
            "rows": [],
            "engine": engine,
            "reason": "missing_window",
            "note": "Phone Link window handle is missing",
        }

    if callable(run_action) and PywinautoEngine is not None and callable(get_automation_config):
        cfg = config or {}
        auto_cfg = get_automation_config(cfg)
        runner = PywinautoEngine(cfg)
        context: dict[str, Any] = {"rows": []}

        def _act(e, ctx: dict[str, Any]) -> bool:
            del e
            rows = extract_messages(win, peer_name=peer_name, limit=limit)
            ctx["rows"] = rows
            return True

        def _verify(e, ctx: dict[str, Any]) -> tuple[bool, str]:
            del e
            rows = ctx.get("rows") if isinstance(ctx.get("rows"), list) else []
            if rows:
                return True, "rows_found"
            return False, "no_message_body_nodes"

        result = run_action(
            "read_messages",
            _act,
            _verify,
            [runner],
            max_attempts_per_engine=int(auto_cfg.get("max_attempts_per_engine", 2)),
            context=context,
        )
        rows = context.get("rows") if isinstance(context.get("rows"), list) else []
        if rows:
            result["ok"] = True
            result["rows"] = rows
            result["engine"] = engine
            result["reason"] = "ok"
            return result
        result["ok"] = False
        result["rows"] = []
        result["engine"] = engine
        result["reason"] = "no_message_body_nodes"
        result["note"] = "thread open in Phone Link but no MessageBody nodes found — scroll the thread"
        return result

    rows = extract_messages(win, peer_name=peer_name, limit=limit)
    if rows:
        return {
            "ok": True,
            "rows": rows,
            "engine": engine,
            "reason": "ok",
            "note": "MessageBody nodes extracted",
        }
    time.sleep(0.1)
    rows = extract_messages(win, peer_name=peer_name, limit=limit)
    if rows:
        return {
            "ok": True,
            "rows": rows,
            "engine": engine,
            "reason": "ok",
            "note": "MessageBody nodes extracted",
        }
    return {
        "ok": False,
        "rows": [],
        "engine": engine,
        "reason": "no_message_body_nodes",
        "note": "thread open in Phone Link but no MessageBody nodes found — scroll the thread",
    }

