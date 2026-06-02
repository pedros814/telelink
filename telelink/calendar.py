"""Calendar CLI — schedule SMS, list events, Google sync."""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime
from typing import Any

from telelink import chalk, pretty
from telelink.calendar_store import CalendarStore
from telelink.calendar_time import format_local_short, format_relative_until, parse_fire_at
from telelink.session import get_session


def _store() -> CalendarStore:
    return CalendarStore(get_session().db)


def _parse_add_args(rest: list[str]) -> tuple[str, str, str, str, str]:
    """name to when message — when may be quoted multi-word."""
    if len(rest) < 3:
        raise ValueError(
            'usage: calendar add <name> <who> <when> <message>\n'
            '       calendar add girlfriend "in 3h" "I love you!"'
        )
    name = rest[0]
    to = rest[1]
    # Find when: try joining from index 2 until parse succeeds
    when = ""
    msg_start = 2
    cfg = get_session().config_fresh()
    for end in range(len(rest), 2, -1):
        candidate = " ".join(rest[2:end])
        try:
            parse_fire_at(candidate, config=cfg)
            when = candidate
            msg_start = end
            break
        except ValueError:
            continue
    if not when:
        when = rest[2]
        msg_start = 3
    message = " ".join(rest[msg_start:])
    if not message:
        raise ValueError("message body is required")
    return name, to, when, message, ""


def cmd_calendar(args: Namespace) -> int:
    config = get_session().config_fresh()
    cal_cfg = config.get("calendar") or {}
    if cal_cfg.get("enabled", True) is False and getattr(args, "calendar_action", None) != "status":
        pretty.warn("calendar is disabled — config edit calendar_enabled true")
        return 1

    action = getattr(args, "calendar_action", None) or "list"
    rest = list(getattr(args, "rest", None) or [])

    if action == "list":
        return _cmd_list(config, all_statuses=getattr(args, "all", False))

    if action == "status":
        return _cmd_status(config)

    if action == "add":
        try:
            if getattr(args, "name", None):
                name = args.name
                to = args.to
                when = args.when
                message = " ".join(args.message) if isinstance(args.message, list) else str(args.message)
            else:
                name, to, when, message, _ = _parse_add_args(rest)
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1
        try:
            event = _store().schedule_send(
                to=to,
                body=message,
                when=when,
                name=name,
                config=config,
                contact_store=get_session().contact_store,
            )
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1
        _print_scheduled(event, config)
        _maybe_google_push(config, event)
        return 0

    if action == "delete":
        name = getattr(args, "name", None) or (rest[0] if rest else "")
        if not name:
            pretty.warn("usage: calendar delete <name>")
            return 1
        event = get_session().db.calendar_get_by_name(name)
        if not event:
            pretty.warn(f"event not found: {name}")
            return 1
        _store().delete_event(name)
        _maybe_google_delete(config, event)
        pretty.info("CALENDAR", f"deleted {name}")
        return 0

    if action == "cancel":
        name = getattr(args, "name", None) or (rest[0] if rest else "")
        if not name:
            pretty.warn("usage: calendar cancel <name>")
            return 1
        ev = _store().cancel_event(name)
        if not ev:
            pretty.warn(f"event not found: {name}")
            return 1
        _maybe_google_delete(config, ev)
        pretty.info("CALENDAR", f"cancelled {name}")
        return 0

    if action == "delay":
        name = getattr(args, "name", None) or (rest[0] if rest else "")
        when = getattr(args, "when", None) or (" ".join(rest[1:]) if len(rest) > 1 else "")
        if not name or not when:
            pretty.warn("usage: calendar delay <name> <when>  —  e.g. calendar delay love-2pm in 1h")
            return 1
        try:
            event = _store().delay_event(name, when, config=config)
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1
        pretty.info("CALENDAR", f"delayed {name}")
        _print_scheduled(event, config)
        _maybe_google_push(config, event)
        return 0

    if action == "event_status":
        name = getattr(args, "name", None) or (rest[0] if rest else "")
        if not name:
            pretty.warn("usage: calendar <name> status")
            return 1
        return _cmd_event_status(name, config)

    if action == "connect":
        sub = rest[0].lower() if rest else ""
        if sub != "google":
            pretty.warn("usage: calendar connect google")
            return 1
        from telelink.calendar_google import connect_google

        try:
            msg = connect_google(config)
            pretty.info("CALENDAR", msg)
        except Exception as exc:
            pretty.warn(str(exc))
            return 1
        return 0

    if action == "sync":
        from telelink.calendar_google import sync_google

        report = sync_google(config, force=True)
        if not report.get("ok") and report.get("error"):
            pretty.warn(str(report["error"]))
            return 1
        pretty.info(
            "CALENDAR",
            f"Google sync — pulled {report.get('pulled', 0)}, pushed {report.get('pushed', 0)}",
        )
        for err in report.get("errors") or []:
            pretty.warn(err)
        return 0

    pretty.warn(f"unknown calendar action: {action}")
    return 1


def dispatch_calendar_command(parts: list[str]) -> int:
    """Parse shell line: calendar [subcommand] …"""
    if not parts:
        return cmd_calendar(Namespace(calendar_action="list"))
    sub = parts[0].lower()
    rest = parts[1:]

    if sub in ("add", "schedule", "new"):
        return cmd_calendar(Namespace(calendar_action="add", rest=rest))
    if sub in ("delete", "remove", "rm"):
        return cmd_calendar(Namespace(calendar_action="delete", name=rest[0] if rest else None, rest=rest))
    if sub == "cancel":
        return cmd_calendar(Namespace(calendar_action="cancel", name=rest[0] if rest else None, rest=rest))
    if sub in ("delay", "snooze", "postpone"):
        return cmd_calendar(Namespace(calendar_action="delay", rest=rest))
    if sub == "status":
        return cmd_calendar(Namespace(calendar_action="status"))
    if sub == "connect":
        return cmd_calendar(Namespace(calendar_action="connect", rest=rest))
    if sub == "sync":
        return cmd_calendar(Namespace(calendar_action="sync"))
    if sub in ("all", "list", "ls"):
        return cmd_calendar(Namespace(calendar_action="list", all=sub == "all"))
    if len(rest) == 1 and rest[0].lower() == "status":
        return cmd_calendar(Namespace(calendar_action="event_status", name=sub, rest=rest))
    if sub == "help":
        from telelink.how_guide import display_help_topic

        display_help_topic(["calendar"])
        return 0
    # calendar <name> status
    if len(parts) >= 2 and parts[-1].lower() == "status":
        name = " ".join(parts[:-1])
        return cmd_calendar(Namespace(calendar_action="event_status", name=name, rest=parts))
    return cmd_calendar(Namespace(calendar_action="list"))


def _cmd_list(config: dict[str, Any], *, all_statuses: bool = False) -> int:
    from telelink.ora import ora
    from telelink.table import calendar_table

    with ora("Loading calendar", kind="load"):
        rows = _store().list_events(all_statuses=all_statuses)
    print(calendar_table(rows, config=config, title=f"calendar ({len(rows)})"))
    print()
    return 0


def _cmd_status(config: dict[str, Any]) -> int:
    from telelink.table import calendar_status_table

    db = get_session().db
    pending = db.calendar_count_pending()
    due = len(db.calendar_pending_due())
    print(calendar_status_table(config, pending=pending, due=due))
    print()
    return 0


def _cmd_event_status(name: str, config: dict[str, Any]) -> int:
    from telelink.table import calendar_event_status_table

    event = get_session().db.calendar_get_by_name(name)
    if not event:
        pretty.warn(f"event not found: {name}")
        return 1
    print(calendar_event_status_table(event, config=config))
    print()
    return 0


def _print_scheduled(event: dict[str, Any], config: dict[str, Any]) -> None:
    when = event["fire_at"]
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    rel = format_relative_until(dt) if dt else when
    local = format_local_short(dt, config=config) if dt else when
    pretty.info("CALENDAR", f"scheduled {event['name']}")
    from telelink.calendar_store import event_receiver_label

    to_line = event["to"]
    contact = event_receiver_label(event)
    if contact and contact != event["to"]:
        to_line = f"{contact} → {event['to']}"
    print(f"  {chalk.muted('to:')} {chalk.value(to_line)}")
    print(f"  {chalk.muted('fires:')} {chalk.value(local)} ({chalk.baby(rel)})")
    print(f"  {chalk.plain(event['body'][:120])}{'…' if len(event['body']) > 120 else ''}")


def _maybe_google_push(config: dict[str, Any], event: dict[str, Any]) -> None:
    from telelink.calendar_google import google_enabled, sync_google

    if google_enabled(config):
        try:
            sync_google(config)
        except Exception:
            pass


def _maybe_google_delete(config: dict[str, Any], event: dict[str, Any]) -> None:
    from telelink.calendar_google import delete_google_event, google_enabled

    if not google_enabled(config) or not event.get("google_event_id"):
        return
    try:
        delete_google_event(config, event)
    except Exception:
        pass

