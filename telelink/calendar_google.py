"""Optional Google Calendar two-way sync."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telelink.calendar_store import calendar_status_is_terminal, slugify_name, unique_name
from telelink.calendar_time import format_fire_at
from telelink.db import Database

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TELELINK_MARKER = "[telelink]"
_META_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


def _google_cfg(config: dict[str, Any]) -> dict[str, Any]:
    cal = config.get("calendar") or {}
    return cal.get("google") or {}


def google_enabled(config: dict[str, Any]) -> bool:
    g = _google_cfg(config)
    return bool(g.get("enabled")) and bool(g.get("credentials_file"))


def _token_path(config: dict[str, Any]) -> Path:
    g = _google_cfg(config)
    out_dir = Path(config["output"]["dir"])
    name = g.get("token_file") or ".calendar-google-token.json"
    return out_dir / name


def _credentials_path(config: dict[str, Any]) -> Path | None:
    raw = str(_google_cfg(config).get("credentials_file") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p if p.exists() else None


def google_available() -> tuple[bool, str]:
    try:
        import google.auth  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401

        return True, ""
    except ImportError:
        return False, "pip install google-api-python-client google-auth-oauthlib"


def _load_credentials(config: dict[str, Any]):
    ok, msg = google_available()
    if not ok:
        raise RuntimeError(msg)
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred_path = _credentials_path(config)
    if not cred_path:
        raise FileNotFoundError(
            "calendar.google.credentials_file not set or missing — download OAuth client JSON from Google Cloud Console"
        )
    token_path = _token_path(config)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), _SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect_google(config: dict[str, Any]) -> str:
    """Run OAuth flow and save token."""
    _load_credentials(config)
    return f"Google Calendar connected — token saved to {_token_path(config)}"


def _service(config: dict[str, Any]):
    from googleapiclient.discovery import build

    creds = _load_credentials(config)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _is_managed_google_event(g_event: dict[str, Any], db: Database) -> bool:
    """Only sync Google events TeleLink created or already linked locally."""
    props = (g_event.get("extendedProperties") or {}).get("private") or {}
    if props.get("telelinkId") or props.get("telelinkName"):
        return True
    if _TELELINK_MARKER in (g_event.get("description") or ""):
        return True
    gid = g_event.get("id") or ""
    if gid:
        for row in db.calendar_list():
            if row.get("google_event_id") == gid:
                return True
    return False


def delete_google_event(config: dict[str, Any], event: dict[str, Any]) -> None:
    """Remove a linked event from Google Calendar (best-effort)."""
    if not google_enabled(config) or not event.get("google_event_id"):
        return
    gcfg = _google_cfg(config)
    service = _service(config)
    service.events().delete(
        calendarId=gcfg.get("calendar_id") or "primary",
        eventId=event["google_event_id"],
    ).execute()


def _parse_meta(description: str) -> dict[str, str]:
    if _TELELINK_MARKER not in description:
        return {}
    block = description.split(_TELELINK_MARKER, 1)[-1].strip()
    meta: dict[str, str] = {}
    for line in block.splitlines():
        m = _META_RE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
    return meta


def _build_description(event: dict[str, Any]) -> str:
    lines = [
        _TELELINK_MARKER,
        f"id: {event['id']}",
        f"name: {event['name']}",
        f"kind: {event.get('kind') or 'send_sms'}",
    ]
    if event.get("to"):
        lines.append(f"to: {event['to']}")
    if event.get("body"):
        lines.append(f"body: {event['body'][:500]}")
    if event.get("notes"):
        lines.append(f"notes: {event['notes']}")
    return "\n".join(lines)


def _google_dt_to_iso(value: dict[str, str] | None, config: dict[str, Any]) -> str:
    if not value:
        raise ValueError("missing event time")
    if "dateTime" in value:
        dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    else:
        from telelink.calendar_time import owner_timezone

        d = value.get("date", "")
        tz = owner_timezone(config)
        dt = datetime.fromisoformat(d).replace(tzinfo=tz)
    return format_fire_at(dt)


def _local_to_google_body(event: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    from telelink.calendar_time import owner_timezone

    tz = str(owner_timezone(config))
    start = event["fire_at"].replace("Z", "+00:00")
    body = {
        "summary": event.get("title") or event["name"],
        "description": _build_description(event),
        "start": {"dateTime": start, "timeZone": tz},
        "end": {
            "dateTime": (datetime.fromisoformat(start) + timedelta(minutes=15)).isoformat(),
            "timeZone": tz,
        },
        "extendedProperties": {
            "private": {"telelinkId": event["id"], "telelinkName": event["name"]},
        },
    }
    return body


def _preserve_local_status(status: str | None) -> bool:
    """Keep completed/failed/in-flight rows out of the pending queue."""
    return calendar_status_is_terminal(status)


def _upsert_local_from_google(
    db: Database,
    g_event: dict[str, Any],
    *,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    gid = g_event.get("id") or ""
    if g_event.get("status") == "cancelled":
        for row in db.calendar_list():
            if row.get("google_event_id") == gid:
                db.calendar_update_status(row["id"], status="cancelled")
        return None

    desc = g_event.get("description") or ""
    meta = _parse_meta(desc)
    props = (g_event.get("extendedProperties") or {}).get("private") or {}
    telelink_id = props.get("telelinkId") or meta.get("id")
    existing = db.calendar_get(telelink_id) if telelink_id else None
    if not existing:
        for row in db.calendar_list():
            if row.get("google_event_id") == gid:
                existing = row
                break

    if not _is_managed_google_event(g_event, db):
        return None

    try:
        fire_at = _google_dt_to_iso(g_event.get("start"), config)
    except ValueError:
        return None

    kind = meta.get("kind") or ("send_sms" if meta.get("to") else "event")
    to_target = meta.get("to") or ""
    body = meta.get("body") or ""
    name = meta.get("name") or slugify_name(g_event.get("summary") or "google-event")
    if existing:
        name = existing["name"]
    else:
        name = unique_name(db, name)

    now = datetime.now(timezone.utc).isoformat()
    event = {
        "id": existing["id"] if existing else (telelink_id if telelink_id and len(telelink_id) > 20 else str(uuid.uuid4())),
        "name": name,
        "title": g_event.get("summary") or name,
        "kind": kind,
        "to": to_target,
        "body": body,
        "fire_at": fire_at,
        "status": (
            existing["status"]
            if existing and _preserve_local_status(existing["status"])
            else "pending"
        ),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "google_event_id": gid,
        "notes": meta.get("notes") or (existing or {}).get("notes", ""),
        "error": "",
        "source": "google",
    }
    db.calendar_upsert(event)
    return event


def sync_google(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Two-way sync with Google Calendar. Returns status dict."""
    if not google_enabled(config):
        return {"ok": False, "error": "calendar.google.enabled is false or credentials_file missing"}

    ok, msg = google_available()
    if not ok:
        return {"ok": False, "error": msg}

    gcfg = _google_cfg(config)
    calendar_id = gcfg.get("calendar_id") or "primary"
    db = Database(config["output"]["sqlite_file"])

    try:
        service = _service(config)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    report = {"pushed": 0, "pulled": 0, "errors": []}

    # Pull from Google
    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                singleEvents=True,
                orderBy="startTime",
                timeMin=datetime.now(timezone.utc).isoformat(),
                maxResults=100,
            )
            .execute()
        )
        for item in result.get("items") or []:
            if _upsert_local_from_google(db, item, config=config):
                report["pulled"] += 1
    except Exception as exc:
        report["errors"].append(f"pull: {exc}")

    # Push local pending to Google
    for event in db.calendar_list(pending_only=True):
        if event.get("source") == "google" and not event.get("google_event_id"):
            continue
        body = _local_to_google_body(event, config)
        try:
            if event.get("google_event_id"):
                service.events().update(
                    calendarId=calendar_id,
                    eventId=event["google_event_id"],
                    body=body,
                ).execute()
            else:
                created = (
                    service.events()
                    .insert(calendarId=calendar_id, body=body)
                    .execute()
                )
                event["google_event_id"] = created.get("id") or ""
                event["updated_at"] = datetime.now(timezone.utc).isoformat()
                db.calendar_upsert(event)
            report["pushed"] += 1
        except Exception as exc:
            report["errors"].append(f"push {event['name']}: {exc}")

    db.kv_set("calendar.google_last_sync", datetime.now(timezone.utc).isoformat())
    report["ok"] = not report["errors"]
    return report


def maybe_sync_google(config: dict[str, Any]) -> None:
    """Background sync if interval elapsed."""
    if not google_enabled(config):
        return
    gcfg = _google_cfg(config)
    interval = gcfg.get("sync_interval", "5m")
    from telelink.duration import parse_duration

    secs = parse_duration(interval) or 300
    db = Database(config["output"]["sqlite_file"])
    last = db.kv_get("calendar.google_last_sync")
    if last:
        try:
            prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - prev).total_seconds()
            if elapsed < secs:
                return
        except (TypeError, ValueError):
            pass
    sync_google(config)


def google_status(config: dict[str, Any]) -> dict[str, Any]:
    gcfg = _google_cfg(config)
    ok, lib_msg = google_available()
    cred = _credentials_path(config)
    token = _token_path(config)
    db = Database(config["output"]["sqlite_file"])
    return {
        "enabled": google_enabled(config),
        "library": ok,
        "library_note": lib_msg,
        "credentials": str(cred) if cred else "",
        "token_saved": token.exists(),
        "calendar_id": gcfg.get("calendar_id") or "primary",
        "last_sync": db.kv_get("calendar.google_last_sync") or "(never)",
    }
