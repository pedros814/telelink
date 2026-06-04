"""ARS command handlers (Phase 2)."""

from __future__ import annotations

import os
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

from telelink import pretty
from telelink.ars_next import build_next_json
from telelink.ars_spawn import (
    clear_ars_pid,
    is_ars_running,
    spawn_ars_window,
    stop_ars,
    write_ars_pid,
)
from telelink.ars_state import transition
from telelink.ars_store import (
    create_session,
    list_sessions,
    load_session,
    normalize_session_name,
    save_session,
)
from telelink.ars_tick import run_ars_tick
from telelink.conout import prepare_ars_console
from telelink.json_out import print_json
from telelink.session import get_session


def _repo_root() -> Path:
    return Path.cwd().resolve()


def _run_path(repo_root: Path) -> str:
    ps1 = repo_root / "telelink.ps1"
    if ps1.is_file():
        return ".\\telelink.ps1"
    return ".\\.venv\\Scripts\\python.exe -m telelink"


def _contact_from_args(args: Namespace) -> str:
    contact = getattr(args, "contact", None)
    if contact is None:
        return ""
    if isinstance(contact, list):
        return " ".join(str(x) for x in contact if str(x).strip()).strip()
    return str(contact).strip()


def _session_from_args(args: Namespace) -> str:
    name = getattr(args, "session", None) or getattr(args, "session_name", None) or ""
    return normalize_session_name(str(name))


def _ars_enabled(config: dict[str, Any]) -> bool:
    return (config.get("ars") or {}).get("enabled", True) is not False


def _caught_matches_session(
    row: dict[str, Any],
    *,
    contact_name: str,
    contact_phone: str,
) -> bool:
    from telelink.contacts import dial_digits

    name = contact_name.lower().strip()
    phone = contact_phone.lower().strip()
    dial = dial_digits(contact_phone)
    r_contact = str(row.get("contact") or "").lower().strip()
    r_sender = str(row.get("sender") or "").lower().strip()
    r_sender_id = dial_digits(str(row.get("sender_id") or row.get("sender") or ""))
    if name and (r_contact == name or r_sender == name):
        return True
    if phone and (r_contact == phone or r_sender == phone):
        return True
    if dial and r_sender_id and (dial in r_sender_id or r_sender_id in dial):
        return True
    return False


def _sleep_poll_with_caught_hint(
    session: dict[str, Any],
    config: dict[str, Any],
    poll_seconds: float,
) -> None:
    """Sleep up to poll_seconds, waking early when caught.jsonl gets a matching SMS."""
    ars_cfg = config.get("ars") or {}
    if ars_cfg.get("use_caught_hint", True) is False:
        time.sleep(max(1.0, poll_seconds))
        return

    from telelink.store import CaughtStore

    out_dir = config.get("output", {}).get("dir", "data")
    caught_file = config.get("output", {}).get("caught_file", "caught.jsonl")
    c_path = Path(out_dir) / caught_file

    def _mtime() -> float:
        return c_path.stat().st_mtime if c_path.exists() else 0.0

    contact = session.get("contact_resolved") or {}
    contact_name = str(contact.get("name") or session.get("contact_query") or "")
    contact_phone = str(contact.get("phone") or session.get("contact_query") or "")

    start_wait = time.monotonic()
    last_mtime = _mtime()

    while time.monotonic() - start_wait < poll_seconds:
        time.sleep(1.0)
        current_mtime = _mtime()
        if current_mtime <= last_mtime:
            continue
        last_mtime = current_mtime
        try:
            store = CaughtStore(str(c_path), str(Path(out_dir) / "attachments"))
            recent = store.list_caught(limit=5)
        except Exception:
            continue
        for row in recent:
            if _caught_matches_session(
                row,
                contact_name=contact_name,
                contact_phone=contact_phone,
            ):
                return


def cmd_ars_start(args: Namespace) -> int:
    tl = get_session()
    config = tl.config_fresh()
    if not _ars_enabled(config):
        pretty.warn("ars is disabled — config edit ars_enabled true")
        return 1

    try:
        session_name = _session_from_args(args)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    contact = _contact_from_args(args)
    if not contact:
        pretty.warn("usage: ars start <session-name> <contact>")
        return 1

    force = getattr(args, "force", False)
    if force:
        stop_ars(session=session_name, force=True)

    try:
        max_turns = getattr(args, "max_turns", 0)
        start_idle = getattr(args, "idle", False)
        no_bootstrap_reply = getattr(args, "no_bootstrap_reply", False)
        
        create_session(
            session_name,
            contact_query=contact,
            config=config,
            contact_store=tl.contact_store,
            max_turns=max_turns if max_turns > 0 else None,
            start_idle=start_idle,
            no_bootstrap_reply=no_bootstrap_reply,
        )
    except Exception as exc:
        pretty.warn(f"failed to create session: {exc}")
        return 1

    if spawn_ars_window(session_name, contact, root=_repo_root()):
        pretty.info("ARS", f"started {session_name} for {contact}")
    else:
        pretty.info("ARS", f"{session_name} already running")
    return 0


def cmd_ars_stop(args: Namespace) -> int:
    tl = get_session()
    config = tl.config_fresh()
    raw = getattr(args, "session", None)

    if raw:
        try:
            session_name = normalize_session_name(str(raw))
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1
        names = [session_name]
    else:
        names = [str(row.get("session") or "") for row in list_sessions(config) if row.get("session")]

    for session_name in names:
        try:
            row = load_session(config, session_name)
            row = transition(row, "stop", {})
            save_session(config, row)
        except FileNotFoundError:
            pass

    ok, msg = stop_ars(session=str(raw) if raw else None, force=True)
    if ok:
        pretty.info("ARS", msg)
        return 0
    pretty.warn(msg)
    return 0 if not names else 0


def cmd_ars_status(args: Namespace) -> int:
    tl = get_session()
    config = tl.config_fresh()
    repo_root = _repo_root()
    run_path = _run_path(repo_root)

    try:
        session_name = _session_from_args(args)
        row = load_session(config, session_name)
    except (ValueError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1

    payload = build_next_json(row, config, repo_root=repo_root, run_path=run_path)
    payload["running"] = is_ars_running(session_name, config)

    if getattr(args, "raw", False):
        print_json(payload)
    else:
        running = "running" if payload.get("running") else "idle"
        pretty.info(
            "ARS",
            f"{session_name}: {payload.get('state')} action={payload.get('action')} ({running})",
        )
    return 0


def cmd_ars_list(args: Namespace) -> int:
    config = get_session().config_fresh()
    rows = list_sessions(config)
    payload = []
    for row in rows:
        name = str(row.get("session") or "")
        payload.append(
            {
                "session": name,
                "state": row.get("state"),
                "contact_query": row.get("contact_query"),
                "updated_at": row.get("updated_at"),
                "running": is_ars_running(name, config) if name else False,
            }
        )

    if getattr(args, "raw", False):
        print_json(payload)
        return 0

    if not payload:
        pretty.info("ARS", "no sessions")
        return 0
    for row in payload:
        running = "running" if row.get("running") else "idle"
        pretty.info(
            "ARS",
            f"{row['session']}: {row.get('state')} ({row.get('contact_query')}) [{running}]",
        )
    return 0


def _run_next(args: Namespace) -> dict[str, Any]:
    tl = get_session()
    config = tl.config_fresh()
    session_name = _session_from_args(args)
    tick = run_ars_tick(session_name, config=config, contact_store=tl.contact_store)
    payload = build_next_json(
        tick.session,
        config,
        repo_root=_repo_root(),
        run_path=_run_path(_repo_root()),
    )
    payload["rows_source"] = tick.rows_source
    payload["rows_count"] = tick.rows_count
    payload["tick_events"] = tick.events
    if tick.error:
        payload["tick_error"] = tick.error
    return payload


def cmd_ars_tick(args: Namespace) -> int:
    try:
        payload = _run_next(args)
    except (ValueError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1

    if getattr(args, "raw", False):
        print_json(payload)
    else:
        pretty.info(
            "ARS",
            f"{payload['session']}: {payload['state']} ({payload.get('reason') or payload['action']})",
        )
    return 0 if payload.get("action") != "error" else 1


def cmd_ars_next(args: Namespace) -> int:
    return cmd_ars_tick(args)


def cmd_ars_run(args: Namespace) -> int:
    tl = get_session()
    config = tl.config_fresh()
    if not _ars_enabled(config):
        pretty.warn("ars is disabled — config edit ars_enabled true")
        return 1

    try:
        session_name = _session_from_args(args)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    contact = _contact_from_args(args)
    if not contact:
        pretty.warn("usage: ars run <session> <contact> --foreground")
        return 1

    if not getattr(args, "foreground", False):
        if spawn_ars_window(session_name, contact, root=_repo_root()):
            pretty.info("ARS", f"started {session_name} for {contact}")
        else:
            pretty.info("ARS", f"{session_name} already running")
        return 0

    os.environ["TELELINK_ARS"] = "1"
    os.environ["TELELINK_ARS_SESSION"] = session_name
    os.environ["TELELINK_ARS_CONTACT"] = contact

    prepare_ars_console()
    write_ars_pid(session_name)

    try:
        create_session(
            session_name,
            contact_query=contact,
            config=config,
            contact_store=tl.contact_store,
        )
    except FileNotFoundError:
        pass
    except Exception:
        try:
            load_session(config, session_name)
        except FileNotFoundError:
            create_session(
                session_name,
                contact_query=contact,
                config=config,
                contact_store=tl.contact_store,
            )

    poll_seconds = float((config.get("ars") or {}).get("poll_interval_seconds") or 45)
    try:
        while True:
            tick = run_ars_tick(session_name, config=config, contact_store=tl.contact_store)
            payload = build_next_json(
                tick.session,
                config,
                repo_root=_repo_root(),
                run_path=_run_path(_repo_root()),
            )
            if getattr(args, "raw", False):
                print_json(payload)
            else:
                pretty.info(
                    "ARS",
                    f"{payload['session']}: {payload['state']} action={payload['action']}",
                )
            if payload.get("action") in ("stopped", "error"):
                return 0 if payload.get("action") != "error" else 1
            poll_seconds = float(payload.get("poll_after_seconds") or poll_seconds)
            session = tick.session
            _sleep_poll_with_caught_hint(session, config, poll_seconds)
    except KeyboardInterrupt:
        pretty.info("ARS", "stopped")
        return 0
    finally:
        clear_ars_pid(session_name)


def cmd_ars_ack(args: Namespace) -> int:
    """Agent acknowledges current turn is complete — §6B."""
    tl = get_session()
    config = tl.config_fresh()

    try:
        session_name = _session_from_args(args)
        session = load_session(config, session_name)
    except (ValueError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1

    state = str(session.get("state") or "")
    force = getattr(args, "force", False)

    if state not in ("need_reply", "awaiting_agent"):
        if force:
            # Force ack from any active state
            ctx: dict[str, Any] = {"force_ack": True}
            session = transition(session, "outbound_detected", ctx)
            save_session(config, session)
            pretty.info("ARS", f"{session_name}: force-acked → {session.get('state')}")
            return 0
        pretty.warn(f"{session_name}: state is {state!r} — ack only works in need_reply or awaiting_agent")
        return 1

    if force:
        ctx = {"force_ack": True}
        session = transition(session, "outbound_detected", ctx)
    else:
        session = transition(session, "agent_ack", {})

    save_session(config, session)
    new_state = str(session.get("state") or "")
    pretty.info("ARS", f"{session_name}: ack → {new_state}")
    return 0


def cmd_ars_pause(args: Namespace) -> int:
    """Pause ARS session poll loop."""
    tl = get_session()
    config = tl.config_fresh()

    try:
        session_name = _session_from_args(args)
        session = load_session(config, session_name)
    except (ValueError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1

    if str(session.get("state") or "") == "paused":
        pretty.info("ARS", f"{session_name}: already paused")
        return 0

    session = transition(session, "pause", {})
    save_session(config, session)
    pretty.info("ARS", f"{session_name}: paused")
    return 0


def cmd_ars_resume(args: Namespace) -> int:
    """Resume a paused ARS session."""
    tl = get_session()
    config = tl.config_fresh()

    try:
        session_name = _session_from_args(args)
        session = load_session(config, session_name)
    except (ValueError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1

    if str(session.get("state") or "") != "paused":
        pretty.info("ARS", f"{session_name}: not paused (state={session.get('state')})")
        return 0

    session = transition(session, "resume", {})
    save_session(config, session)
    pretty.info("ARS", f"{session_name}: resumed → {session.get('state')}")
    return 0


def cmd_ars_wait(args: Namespace) -> int:
    """Block until session action becomes ``reply`` or ``stopped``."""
    tl = get_session()
    config = tl.config_fresh()
    repo_root = _repo_root()
    run_path = _run_path(repo_root)

    try:
        session_name = _session_from_args(args)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    # Parse timeout
    timeout_raw = getattr(args, "timeout", None)
    timeout_secs: float | None = None
    if timeout_raw:
        try:
            from telelink.duration import parse_duration
            timeout_secs = float(parse_duration(timeout_raw))
        except Exception:
            try:
                timeout_secs = float(timeout_raw)
            except ValueError:
                pretty.warn(f"invalid timeout: {timeout_raw!r}")
                return 1

    raw = getattr(args, "raw", False)
    start = time.monotonic()

    try:
        while True:
            tick = run_ars_tick(session_name, config=config, contact_store=tl.contact_store)
            payload = build_next_json(
                tick.session,
                config,
                repo_root=repo_root,
                run_path=run_path,
            )
            action = payload.get("action")
            if action in ("reply", "stopped", "error"):
                if raw:
                    print_json(payload)
                else:
                    pretty.info(
                        "ARS",
                        f"{session_name}: {payload['state']} action={action}",
                    )
                return 0 if action != "error" else 1

            if timeout_secs is not None:
                elapsed = time.monotonic() - start
                if elapsed >= timeout_secs:
                    if raw:
                        payload["timed_out"] = True
                        print_json(payload)
                    else:
                        pretty.info("ARS", f"{session_name}: wait timed out ({timeout_raw})")
                    return 0

            poll = float(payload.get("poll_after_seconds") or 45)
            _sleep_poll_with_caught_hint(tick.session, config, max(2.0, min(poll, 60.0)))
    except KeyboardInterrupt:
        pretty.info("ARS", f"{session_name}: wait interrupted")
        return 0

