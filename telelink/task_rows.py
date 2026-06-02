"""Normalize task JSONL rows (legacy client → contact)."""

from __future__ import annotations

from typing import Any


def normalize_task_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "contact" not in out and "client" in out:
        out["contact"] = out["client"]
    if "contact_matched" not in out and "is_client" in out:
        out["contact_matched"] = out["is_client"]
    return out


def task_contact(row: dict) -> str:
    return str(row.get("contact") or row.get("client") or "").strip()


def task_matched(row: dict) -> bool:
    if "contact_matched" in row:
        return bool(row.get("contact_matched"))
    return bool(row.get("is_client"))
