from __future__ import annotations



import argparse
from argparse import Namespace

import json

import sys

from pathlib import Path



from telelink import __version__, chalk, pretty

from telelink.config import load_config
from telelink.session import get_session
from telelink.service import TeleLinkService





def _safe_print(text: str) -> None:

    try:

        print(text)

    except UnicodeEncodeError:

        print(text.encode("ascii", errors="replace").decode("ascii"))





def cmd_shell(_args: argparse.Namespace) -> int:

    from telelink.console import run_shell



    return run_shell()





def cmd_watcher_stop(_args: argparse.Namespace) -> int:
    from telelink.listener_spawn import stop_watcher

    ok, msg = stop_watcher(force=True)
    if ok:
        pretty.info("WATCHER", msg)
    else:
        pretty.warn(msg)
    return 0 if ok else 1


def cmd_watcher(args: argparse.Namespace) -> int:
    from pathlib import Path

    if getattr(args, "watcher_action", None) == "stop":
        return cmd_watcher_stop(args)

    from telelink.listener_spawn import spawn_watcher_window

    root = Path.cwd()
    if getattr(args, "foreground", False):
        import os

        os.environ["TELELINK_WATCHER"] = "1"
        get_session()
        TeleLinkService().run_sync()
        return 0

    if spawn_watcher_window(root=root, background=True):
        pretty.info("WATCHER", "started in background (minimized)")
    else:
        pretty.info("WATCHER", "already running")
    return 0





def cmd_caught(args: argparse.Namespace) -> int:

    from telelink.gron import gron_caught

    from telelink.ora import ora

    from telelink.table import full_records_table, caught_table



    contact = getattr(args, "contact", None) or getattr(args, "client", None)

    contacts_only = getattr(args, "contacts_only", False) or getattr(args, "clients_only", False)



    with ora("Loading caught", kind="load"):

        session = get_session()
        config = session.config_fresh()
        from telelink.store import CaughtStore
        store = session.caught_store

        rows = store.list_caught(

            limit=None if args.group else args.limit,

            channel=args.channel,

            contact=contact,

            sender=args.sender,

            message_kind=args.kind,

            contacts_only=contacts_only,

        )



    if args.group:

        groups = CaughtStore.group_caught(rows, args.group)

        if getattr(args, "raw", False):

            print(json.dumps(groups, indent=2, ensure_ascii=False))

        elif getattr(args, "gron", False):

            parts = []

            for key in sorted(groups.keys()):

                items = groups[key][-args.limit :] if args.limit else groups[key]

                parts.append(gron_caught(items, root=key))

            _safe_print("\n\n".join(parts) if parts else "json = [];")

        elif args.json:

            parts = []

            for key in sorted(groups.keys()):

                items = groups[key][-args.limit :] if args.limit else groups[key]

                parts.append(full_records_table(items, title=f"{key} ({len(items)})"))

            _safe_print("\n\n".join(parts) if parts else "(nothing caught yet)")

        else:

            parts = []

            for key in sorted(groups.keys()):

                items = groups[key][-args.limit :] if args.limit else groups[key]

                parts.append(caught_table(items, title=f"{key} ({len(items)})"))

            _safe_print("\n\n".join(parts) if parts else "(nothing caught yet)")

        return 0



    if args.limit:

        rows = rows[-args.limit :]

    if getattr(args, "raw", False):
        from telelink.json_out import print_json

        print_json(rows, indent=2)

    elif getattr(args, "gron", False):

        _safe_print(gron_caught(rows) if rows else "json = [];")

    elif args.json:

        _safe_print(full_records_table(rows))

    else:

        _safe_print(caught_table(rows) if rows else "(nothing caught yet)")

    return 0





def cmd_sync(args: argparse.Namespace) -> int:
    from telelink.ora import ora
    from telelink.session import get_session
    from telelink.sync import format_sync_summary, run_full_sync

    with ora("Re-syncing Phone Link, contacts, jsonl, and sqlite", kind="load"):
        session = get_session()
        report = run_full_sync(
            session,
            import_caught=bool(getattr(args, "caught", False)),
            force=True,
            quiet=True,
        )
    pretty.info("SYNC", format_sync_summary(report))
    if report.phone_link_db_path:
        pretty.info(
            "SYNC",
            f"Phone Link contacts.db: {report.phone_link_contacts_db} rows "
            f"({report.phone_link_message_dbs} message/photo DBs)",
        )
    elif report.phone_link_contacts_db <= 0:
        pretty.warn("Phone Link contacts.db not found — open Phone Link and sync from iPhone")
    return 0


def cmd_intake_stop(_args: argparse.Namespace) -> int:
    from telelink.intake_runtime import stop_intake_server

    ok, msg = stop_intake_server(config=load_config())
    if ok:
        pretty.info("INTAKE", msg)
    else:
        pretty.warn(msg)
    return 0 if ok else 1


def cmd_intake(args: argparse.Namespace) -> int:
    from telelink.intake_runtime import run_intake_session

    action = getattr(args, "intake_action", None)
    if action == "stop":
        return cmd_intake_stop(args)

    global_mode = action == "global" or getattr(args, "global_mode", False)
    mode = None
    if getattr(args, "sms", False):
        mode = "sms"
    elif getattr(args, "qr", False):
        mode = "qr"
    return run_intake_session(
        mode=mode,
        block=getattr(args, "wait", False),
        global_mode=global_mode,
        config=load_config(),
    )


def cmd_airdrop(args: argparse.Namespace) -> int:
    from telelink.airdrop_send import (
        airdrop_availability,
        format_receivers_table,
        platform_airdrop_note,
        print_airdrop_intro,
        resolve_receiver,
        run_find,
        send_paths,
    )
    from telelink.config import load_config

    print_airdrop_intro()
    config = load_config()
    parts = getattr(args, "target", None) or []

    ok, note = airdrop_availability(config)
    if not ok:
        pretty.warn(note)
        pretty.info("AIRDROP", f"OpenDrop: https://github.com/seemoo-lab/opendrop")
        pretty.info("AIRDROP", "On Windows: set airdrop.mode ssh + airdrop.ssh.host to a Mac/Linux helper")
        return 1

    if not parts:
        timeout = getattr(args, "find_timeout", None)
        pretty.info("AIRDROP", f"scanning for receivers … ({note})")
        try:
            receivers = run_find(config, timeout=timeout)
        except (TimeoutError, FileNotFoundError, OSError) as exc:
            pretty.warn(str(exc))
            return 1
        if not receivers:
            pretty.warn("no receivers found")
            pretty.info("AIRDROP", platform_airdrop_note())
            pretty.info("AIRDROP", "iPhone: Control Center → AirDrop → Everyone, keep screen on")
            return 1
        print(flush=True)
        print(format_receivers_table(receivers), flush=True)
        print(flush=True)
        pretty.info(
            "AIRDROP",
            'send: airdrop "Receiver Name" C:\\path\\to\\file.png',
        )
        return 0

    if len(parts) < 2:
        pretty.warn('usage: airdrop "Receiver Name" <file|url> [file ...]')
        pretty.warn("  run airdrop alone first to list receivers")
        return 1

    receiver_query = parts[0]
    file_parts = parts[1:]
    try:
        receivers = run_find(config, timeout=8)
    except (TimeoutError, FileNotFoundError, OSError):
        receivers = []
    from telelink.airdrop_send import read_discovery_cache

    if not receivers:
        receivers = read_discovery_cache(config)
    try:
        receiver = resolve_receiver(receiver_query, receivers, config)
        send_paths(file_parts, receiver, config)
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
        pretty.warn(str(exc))
        return 1
    return 0


def cmd_outtake(args: argparse.Namespace) -> int:
    from telelink.config import load_config
    from telelink.intake_runtime import normalize_share_url
    from telelink.outtake_share import (
        confirm_public_outtake,
        prepare_share_file,
        resolve_local_paths,
        share_file,
    )
    from telelink.share_delivery import run_share_delivery, share_link_sms_body

    parts = getattr(args, "target", None) or getattr(args, "url", None) or []
    if not parts:
        pretty.warn("usage: outtake <url>   or   outtake <file> [file ...]")
        pretty.warn("  e.g. outtake www.youtube.com   outtake C:\\docs\\brief.pdf")
        pretty.warn("  multiple files are zipped: outtake a.pdf b.png")
        pretty.warn("  PC → iPhone direct: outtake file.pdf --airdrop")
        return 1

    mode = None
    if getattr(args, "sms", False):
        mode = "sms"
    elif getattr(args, "qr", False):
        mode = "qr"

    config = load_config()
    use_airdrop = getattr(args, "airdrop", False)
    is_file = False
    locals_ = resolve_local_paths(parts)
    if locals_ is not None:
        from telelink.airdrop_send import (
            airdrop_availability,
            outtake_prefers_airdrop,
            resolve_receiver,
            run_find,
            send_paths,
        )
        from telelink.airdrop_send import read_discovery_cache

        if use_airdrop or outtake_prefers_airdrop(config, force=use_airdrop):
            ok, note = airdrop_availability(config)
            if not ok:
                pretty.warn(f"airdrop unavailable: {note}")
                if use_airdrop:
                    return 1
            else:
                ad = config.get("airdrop") or {}
                receiver = (ad.get("default_receiver") or "").strip()
                if not receiver:
                    pretty.warn(
                        'set airdrop.default_receiver in config, or: '
                        'outtake file.pdf --airdrop "John\'s iPhone"'
                    )
                    receivers = run_find(config, timeout=12)
                    if not receivers:
                        receivers = read_discovery_cache(config)
                    if receivers:
                        from telelink.airdrop_send import format_receivers_table

                        print(format_receivers_table(receivers), flush=True)
                    else:
                        pretty.warn("no receivers — run airdrop first")
                    return 1
                try:
                    receivers = read_discovery_cache(config) or run_find(config, timeout=8)
                    resolved = resolve_receiver(receiver, receivers, config)
                    send_paths([str(p) for p in locals_], resolved, config)
                    return 0
                except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
                    pretty.warn(str(exc))
                    if use_airdrop:
                        return 1
                    pretty.info("OUTTAKE", "falling back to GitHub share …")

        if not confirm_public_outtake(locals_, config=config):
            pretty.warn("outtake cancelled")
            return 0
        is_file = True
        upload, is_temp = prepare_share_file(locals_)
        zip_label = upload.name if is_temp else None
        try:
            target = share_file(upload, config)
        except (OSError, ValueError, RuntimeError) as exc:
            pretty.warn(str(exc))
            hint = str(exc).lower()
            if "owner" in hint and "repo" in hint and "config" in hint:
                pretty.info("OUTTAKE", "set outtake.github in config.yaml (token, owner, repo)")
            elif "404" in hint or "not found" in hint or "does not exist" in hint:
                pretty.info(
                    "OUTTAKE",
                    "create the GitHub repo named in config (or fix owner/repo spelling)",
                )
            return 1
        finally:
            if is_temp:
                upload.unlink(missing_ok=True)
        if len(locals_) == 1:
            pretty.info("OUTTAKE", f"uploaded {locals_[0].name}")
        else:
            names = ", ".join(p.name for p in locals_)
            pretty.info(
                "OUTTAKE",
                f"uploaded {len(locals_)} files as {zip_label} ({names})",
            )
    else:
        try:
            target = normalize_share_url(" ".join(parts))
        except ValueError as exc:
            pretty.warn(str(exc))
            return 1

    if is_file:
        sms_body = share_link_sms_body("TeleLink download", target)
        qr_caption = "Scan to download"
        qr_hint = "scan to download on your phone"
    else:
        sms_body = share_link_sms_body("TeleLink link", target)
        qr_caption = "Scan to open"
        qr_hint = "scan with your phone to open"

    print(flush=True)
    run_share_delivery(
        target,
        config=config,
        mode=mode,
        prompt="How do you want to share the link?",
        qr_caption=qr_caption,
        tag="OUTTAKE",
        qr_hint=qr_hint,
        sms_body=sms_body,
    )
    return 0





def _contacts_store():

    return get_session().contact_store





def cmd_contacts(args: argparse.Namespace) -> int:

    from telelink.ora import ora

    from telelink.table import contacts_table



    with ora("Loading contacts", kind="load"):

        session = get_session()

        config = session.config_fresh()

        store = session.contact_store

        store.reload_from_disk()



    if getattr(args, "sync_config", False):

        n = store.sync_from_config(config)
        session.on_contacts_changed()
        pretty.info("SYNC", f"{n} new from config.yaml")



    if getattr(args, "sync_caught", False):

        tasks = session.caught_store.list_caught()

        n = store.sync_from_caught(tasks)

        session.on_contacts_changed()

        pretty.info("SYNC", f"{n} new from caught")



    if getattr(args, "add_name", None):

        match_raw = getattr(args, "match", "") or ""

        match_list = [m.strip() for m in match_raw.split(",") if m.strip()] if match_raw else None

        store.upsert(

            name=args.add_name,

            phone=getattr(args, "phone", "") or "",

            match=match_list,

            platform=getattr(args, "platform", "") or "",

            notes=getattr(args, "notes", "") or "",

            managed=not getattr(args, "personal", False),

        )

        session.on_contacts_changed()

        pretty.info("SAVED", args.add_name)



    if getattr(args, "remove", None):

        if store.remove(args.remove):

            session.on_contacts_changed()

            pretty.info("REMOVED", args.remove)

        else:

            pretty.warn(f"contact not found: {args.remove}")

            return 1



    rows = store.list_contacts(query=getattr(args, "search", None))

    _safe_print(contacts_table(rows, title=f"contacts ({len(rows)})"))

    print(f"\n  file: {chalk.value(str(config['output']['contacts_file']))}\n")

    return 0





def cmd_send(args: argparse.Namespace) -> int:
    from telelink.send_parse import parse_send_tokens, run_send_intent

    payload = list(getattr(args, "payload", None) or [])
    if not payload and getattr(args, "to", None):
        payload = [args.to] + list(getattr(args, "message", None) or [])

    try:
        intent = parse_send_tokens(payload)
    except ValueError as exc:
        pretty.warn(str(exc))
        return 1

    return run_send_intent(intent)





def cmd_config_reset(args: argparse.Namespace) -> int:
    from telelink.config_edit import config_reset, example_config_path
    from telelink.prompts import confirm_choice

    example = example_config_path()
    if not getattr(args, "yes", False):
        if not confirm_choice(
            title="Reset config",
            details=[
                f"Replace config.yaml with {example.name}.",
                "Your current settings (tokens, owner, paths) will be lost.",
            ],
            yes_label="Yes — reset config.yaml",
            no_label="No — keep current config",
        ):
            pretty.info("CONFIG", "reset cancelled")
            return 0

    try:
        dest = config_reset()
    except FileNotFoundError as exc:
        pretty.warn(str(exc))
        return 1

    pretty.info("CONFIG", f"reset → {dest.name} (from {example.name})")
    return 0


def cmd_wipe(args: argparse.Namespace) -> int:
    from telelink import pretty
    from telelink.prompts import confirm_choice
    from telelink.session import get_session, reset_session
    from telelink.wipe_data import (
        ALL_TARGETS,
        resolve_wipe_targets,
        wipe_target_names,
        wipe_targets,
    )

    raw = getattr(args, "target", None) or []
    if isinstance(raw, str):
        raw = [raw]
    targets = resolve_wipe_targets(list(raw))
    if not targets:
        names = ", ".join(wipe_target_names())
        pretty.warn(f"usage: wipe <target> [target …]  —  targets: {names}")
        pretty.warn("example: wipe caught  ·  wipe sent contacts  ·  wipe all --yes")
        return 1

    label = (
        "all local TeleLink data"
        if set(targets) == set(ALL_TARGETS)
        else ", ".join(targets)
    )

    if not getattr(args, "yes", False):
        if not confirm_choice(
            title="Wipe local data",
            details=[
                f"Clear: {label}.",
                "config.yaml is kept. This cannot be undone.",
            ],
            yes_label="Yes — delete data",
            no_label="No — keep data",
        ):
            pretty.info("WIPE", "cancelled")
            return 0

    session = get_session()
    report = wipe_targets(session.config, targets, session=session)
    reset_session()

    if not report.ok:
        pretty.warn("nothing was cleared")
        for skip in report.skipped:
            pretty.warn(skip)
        return 1

    for line in report.cleared:
        pretty.info("WIPE", line)
    for skip in report.skipped:
        pretty.warn(skip)
    return 0


def cmd_calls(args: argparse.Namespace) -> int:
    action = getattr(args, "calls_action", None)
    if action == "sync":
        from telelink.calls import cmd_calls_sync as _run

        return _run(args)
    from telelink.calls import cmd_calls as _run

    return _run(args)


def cmd_convo(args: argparse.Namespace) -> int:
    from telelink.convo import cmd_convo as _cmd_convo

    return _cmd_convo(args)


def cmd_zns(args: argparse.Namespace) -> int:
    from telelink.zeronoshow_bridge import cmd_zns as _cmd_zns

    return _cmd_zns(args)


def cmd_received(args: argparse.Namespace) -> int:
    from telelink.received import cmd_received as _cmd_received

    return _cmd_received(args)


def cmd_missed(args: argparse.Namespace) -> int:
    from telelink.calls import cmd_missed as _run

    return _run(args)


def cmd_calendar(args: argparse.Namespace) -> int:
    from telelink.calendar import cmd_calendar as _run

    return _run(args)


def cmd_agent(args: argparse.Namespace) -> int:
    from telelink.agent import cmd_agent as _run

    return _run(args)


def cmd_how(args: argparse.Namespace) -> int:
    from telelink.how_guide import display_help_topic, render_how_guide

    topic = getattr(args, "topic", None) or []
    if topic:
        display_help_topic(topic)
        return 0
    print(render_how_guide())
    return 0


def cmd_ars(args: argparse.Namespace) -> int:
    from telelink import ars_cli
    action = getattr(args, "ars_action", None) or "list"
    if action == "start": return ars_cli.cmd_ars_start(args)
    if action == "stop": return ars_cli.cmd_ars_stop(args)
    if action == "status": return ars_cli.cmd_ars_status(args)
    if action == "list": return ars_cli.cmd_ars_list(args)
    if action == "next": return ars_cli.cmd_ars_next(args)
    if action == "tick": return ars_cli.cmd_ars_tick(args)
    if action == "run": return ars_cli.cmd_ars_run(args)
    if action == "ack": return ars_cli.cmd_ars_ack(args)
    if action == "pause": return ars_cli.cmd_ars_pause(args)
    if action == "resume": return ars_cli.cmd_ars_resume(args)
    if action == "wait": return ars_cli.cmd_ars_wait(args)
    if action == "delete":
        from telelink.ars_store import delete_session, normalize_session_name
        for target in getattr(args, "session_list", []):
            delete_session(normalize_session_name(target))
        return 0
    from telelink import pretty
    pretty.warn(f"unknown ars command: {action!r}")
    return 1


def cmd_config_edit(args: argparse.Namespace) -> int:
    from telelink.config_edit import config_edit, format_config_value, suggest_keys
    from telelink.config_edit import flatten_config, load_raw_config

    value_parts = getattr(args, "value", None) or []
    if isinstance(value_parts, str):
        value_parts = [value_parts]
    try:
        dotted, old, new = config_edit(args.key, list(value_parts))
    except (ValueError, KeyError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        try:
            flat = flatten_config(load_raw_config())
            hints = suggest_keys(args.key, flat)
            if hints:
                pretty.info("CONFIG", f"did you mean: {', '.join(hints)}?")
        except FileNotFoundError:
            pass
        return 1

    old_s = format_config_value(old)
    new_s = format_config_value(new)
    pretty.info("CONFIG", f"{dotted} = {new_s}")
    if old is not None and old != new:
        print(f"  {chalk.muted('was:')} {chalk.value(old_s)}")
    print(f"  {chalk.muted('saved:')} {chalk.value('config.yaml')}")
    return 0


def cmd_config_get(args: argparse.Namespace) -> int:
    from telelink.config_edit import config_get, format_config_value

    try:
        dotted, value = config_get(args.key)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        pretty.warn(str(exc))
        return 1
    pretty.info("CONFIG", f"{dotted} = {format_config_value(value)}")
    return 0


def cmd_config_list(_args: argparse.Namespace) -> int:
    from telelink.config_edit import config_list_keys, format_config_value

    try:
        rows = config_list_keys()
    except FileNotFoundError as exc:
        pretty.warn(str(exc))
        return 1
    if not rows:
        pretty.warn("config.yaml is empty")
        return 0
    section = ""
    for path, value in rows:
        head = path.split(".", 1)[0]
        if head != section:
            section = head
            _safe_print(chalk.label(section))
        _safe_print(f"  {chalk.muted(path)} = {chalk.value(format_config_value(value))}")
    _safe_print(f"\n  {chalk.muted('edit:')} {pretty.command('config edit <key> <value>')}\n")
    return 0


def cmd_config_show(_args: argparse.Namespace) -> int:

    from telelink.config import discover_phone_link_folders

    from telelink.ora import ora



    with ora("Loading config", kind="load"):

        session = get_session()

        config = session.config_fresh()

    pretty.info("CONFIG", f"TeleLink {__version__}")

    _safe_print(chalk.label("Output"))

    out = config["output"]

    _safe_print(f"  caught: {chalk.value(str(out['caught_file']))}")

    _safe_print(f"  contacts: {chalk.value(str(out['contacts_file']))}")

    _safe_print(f"  sqlite: {chalk.value(str(out['sqlite_file']))}")

    _safe_print(f"  localstorage: {chalk.value(str(out['localstorage_file']))}")

    _safe_print(f"  attachments: {chalk.value(str(out['attachments_dir']))}")

    from telelink.duration import format_duration
    from telelink.call_log import call_log_enabled, call_log_ttl_seconds

    if call_log_enabled(config):
        call_ttl = call_log_ttl_seconds(config)
        _safe_print(
            f"  calls: {chalk.value(str(out.get('calls_file', '')))} "
            f"(ttl {format_duration(call_ttl)})"
        )
    else:
        _safe_print(f"  calls: {chalk.value('off')}")
    from telelink.analyze_snapshot import analyze_dir, analyze_options, screenshot_enabled

    if screenshot_enabled(config):
        aopts = analyze_options(config)
        adir = analyze_dir(config)
        ttl_a = aopts.get("ttl_seconds")
        ttl_label = format_duration(ttl_a) if ttl_a else "off"
        _safe_print(
            f"  analyze: {chalk.value(str(adir))} "
            f"({aopts['width']}x{aopts['height']}, ttl {ttl_label})"
        )
    else:
        _safe_print(f"  analyze: {chalk.value('off')}")

    ttl = out.get("auto_delete_caught_seconds")
    if ttl:
        _safe_print(f"  auto_delete_caught: {chalk.value(format_duration(ttl))}")
    else:
        _safe_print(f"  auto_delete_caught: {chalk.value('off (no expiry)')}")
    from telelink.sent_log import sent_log_max_entries, sent_log_path

    msg = config.get("messaging") or {}
    if msg.get("log_sent", True):
        sent_max = sent_log_max_entries(config)
        sent_label = str(sent_max) if sent_max else "off (unlimited)"
        _safe_print(
            f"  sent log: {chalk.value(str(sent_log_path(config)))} "
            f"(max {chalk.value(sent_label)} entries)"
        )
    else:
        _safe_print(f"  sent log: {chalk.value('off (log_sent false)')}")
    _safe_print("")

    automation = config.get("automation") or {}
    automation_enabled = automation.get("enabled", True)
    if isinstance(automation_enabled, str):
        automation_enabled = automation_enabled.strip().lower() in ("1", "true", "yes", "on")
    if automation_enabled:
        _safe_print(chalk.label("Automation"))
        try:
            from telelink.ui_automation.doctor import (
                check_automation_health,
                format_doctor_report,
            )

            report = check_automation_health(config)
            for line in format_doctor_report(report).splitlines():
                _safe_print(f"  {line}")
        except Exception as exc:
            _safe_print(f"  status: {chalk.value('WARN')}")
            _safe_print(f"  [WARN] automation_doctor: {chalk.muted(str(exc))}")
        _safe_print("")

    if session.sync_report:

        from telelink.sync import format_sync_summary
        from telelink.sync_auto import auto_sync_enabled, auto_sync_interval_seconds

        sr = session.sync_report

        _safe_print(f"{chalk.label('Last sync')}: {chalk.value(format_sync_summary(sr))}")

        sync_cfg = config.get("sync") or {}
        if auto_sync_enabled(config):
            interval = auto_sync_interval_seconds(config)
            from telelink.duration import format_duration

            _safe_print(
                f"  {chalk.muted('auto-sync')}: "
                f"{chalk.value('on')} every {chalk.value(format_duration(interval))}"
            )
        else:
            _safe_print(f"  {chalk.muted('auto-sync')}: {chalk.value('off')}")

        last_full = session.local_storage.last_sync("full")
        if last_full:
            _safe_print(f"  {chalk.muted('last full sync')}: {chalk.value(last_full)}")

    cstore = session.contact_store

    contacts = cstore.list_contacts()

    _safe_print(f"{chalk.label('Contacts')}: {chalk.value(str(len(contacts)))} in contacts.jsonl")

    for c in contacts:

        managed = "managed" if c.get("managed", True) else "personal"

        match_n = len(c.get("match") or [])

        _safe_print(

            f"  - {chalk.value(str(c.get('name')))} "

            f"({chalk.value(managed)}, {chalk.value(str(match_n))} match rules)"

        )



    from telelink.classify import get_owner, unmatched_contact_label



    owner = get_owner(config)

    if owner and not owner.get("_legacy"):

        _safe_print(chalk.label("\nOwner (you)"))

        _safe_print(f"  business: {chalk.value(str(owner.get('business_name', '')))}")

        _safe_print(f"  name: {chalk.value(str(owner.get('personal_name_full') or owner.get('personal_name_short', '')))}")

        _safe_print(f"  email: {chalk.value(str(owner.get('work_email', '')))}")

        _safe_print(f"  timezone: {chalk.value(str(owner.get('timezone', '')))}")



    _safe_print(f"\n{chalk.label('Routing')}")

    r = config.get("routing", {})

    _safe_print(f"  unmatched -> {chalk.value(unmatched_contact_label(config))}")

    only = r.get("only_contacts", r.get("only_clients", False))

    _safe_print(f"  only_contacts: {chalk.value(str(only))}")

    _safe_print(f"  ignore_channels: {chalk.value(str(r.get('ignore_channels', [])))}")

    from telelink.config import watcher_auto_start_enabled

    listener = config.get("listener") or {}
    auto_w = watcher_auto_start_enabled(config)
    from telelink.duration import format_duration

    _safe_print(f"\n{chalk.label('Watcher')}")
    start_delay = listener.get("auto_start_delay_seconds")
    delay_label = format_duration(start_delay) if auto_w and start_delay else "—"
    _safe_print(
        f"  auto_start_window: {chalk.value('on' if auto_w else 'off')} "
        f"(delay {chalk.value(delay_label if auto_w else '—')}, minimizes to background)"
    )
    nudge = listener.get("console_nudge", True) is not False
    nudge_secs = listener.get("console_nudge_interval_seconds") or 0

    nudge_label = format_duration(nudge_secs) if nudge and nudge_secs else "off"
    _safe_print(
        f"  console_nudge: {chalk.value(nudge_label)} "
        f"({chalk.muted('config edit watcher_nudge_interval 45s')})"
    )
    _safe_print(f"  poll_seconds: {chalk.value(str(listener.get('poll_seconds', 2)))}")

    _safe_print(f"\n{chalk.label('Watch folders')}")

    with ora("Scanning Phone Link folders", kind="scan"):

        discovered = discover_phone_link_folders()

    for folder in config.get("phone_link", {}).get("watch_folders", []):

        tag = "OK" if Path(folder).exists() else "MISSING"

        src = "auto" if folder in discovered else "config"

        _safe_print(f"  {chalk.baby(f'[{tag}]')} ({chalk.value(src)}) {chalk.value(str(folder))}")



    _safe_print(f"\n{chalk.label('OCR')}: {chalk.value('enabled' if config.get('ocr', {}).get('enabled') else 'disabled')}")

    from telelink.harvest import find_phone_link_databases
    from telelink.phone_link_contacts import describe_contacts_db_discovery, get_phone_link_contact_index
    from telelink.phone_link_messages import describe_phone_db_status
    from telelink.phone_link_fallback import fallback_status



    h = config.get("harvest", {})

    with ora("Scanning Phone Link databases", kind="scan"):

        dbs = find_phone_link_databases()
        pl_info = describe_contacts_db_discovery(
            config, local_storage=session.local_storage
        )
        pl_count = get_phone_link_contact_index(config, local_storage=session.local_storage).load(
            config, force=True, local_storage=session.local_storage
        )
        phone_db = describe_phone_db_status(config, local_storage=session.local_storage)

    fb = fallback_status(config)
    _safe_print(
        f"\n{chalk.label('Path fallback')}: "
        f"{chalk.value(str(fb.get('label', 'off')))}"
    )
    if fb.get("enabled"):
        _safe_print(
            f"  {chalk.muted('engine')}: {chalk.value(str(fb.get('engine')))} "
            f"({chalk.value(str(fb.get('package_roots', 0)))} package roots)"
        )

    _safe_print(
        f"\n{chalk.label('Phone Link contacts.db')}: "
        f"{chalk.value(str(pl_count))} contacts"
    )
    _safe_print(
        f"  {chalk.muted('discovery_method')}: "
        f"{chalk.value(str(pl_info.get('discovery_method', 'none')))}"
    )
    chosen = pl_info.get("chosen")
    if chosen:
        _safe_print(f"  {chalk.muted('using')} {chalk.value(chosen)}")
    else:
        _safe_print(
            f"  {chalk.value('not found')} — {chalk.muted('open Phone Link on Windows and sync contacts from iPhone')}"
        )
    alts = [c for c in pl_info.get("candidates") or [] if not c.get("chosen")]
    if len(alts) > 0:
        _safe_print(f"  {chalk.muted('other device DBs found:')} {chalk.value(str(len(alts)))}")

    if phone_db.get("found"):
        _safe_print(
            f"{chalk.label('Phone Link phone.db')}: "
            f"{chalk.value(str(phone_db.get('message_rows', 0)))} messages"
        )
        _safe_print(
            f"  {chalk.muted('discovery_method')}: "
            f"{chalk.value(str(phone_db.get('discovery_method', 'none')))}"
        )
        _safe_print(f"  {chalk.muted('using')} {chalk.value(str(phone_db.get('path')))}")
    else:
        _safe_print(f"{chalk.label('Phone Link phone.db')}: {chalk.value('not synced yet')}")
        _safe_print(
            f"  {chalk.muted('discovery_method')}: "
            f"{chalk.value(str(phone_db.get('discovery_method', 'none')))}"
        )
        if phone_db.get("expected_dir"):
            expected = Path(phone_db["expected_dir"]) / "phone.db"
            _safe_print(
                f"  {chalk.muted('open Phone Link → Messages — file appears at')} "
                f"{chalk.value(str(expected))}"
            )

    _safe_print(f"{chalk.label('Auto-harvest')}: {chalk.value('on' if h.get('enabled', True) else 'off')} ({chalk.value(str(len(dbs)))} message/photo DBs)")

    if not dbs:

        _safe_print(f"  {chalk.muted('No photos.db yet - use iOS automation:')} {chalk.value('assets/ios-auto-intake.txt')}")

    ip = config.get("iphone_pull", {})

    _safe_print(f"{chalk.label('iPhone DCIM pull')}: {chalk.value('on' if ip.get('enabled') else 'off')}")

    intake = config.get("intake", {})

    if intake.get("enabled", True):

        from telelink.intake import get_lan_ip



        port = int(intake.get("port", 8787))

        _safe_print(f"\n{chalk.label('Intake (LAN share)')}: {pretty.link(f'http://{get_lan_ip()}:{port}/')}")

        _safe_print(f"  {chalk.muted('Guide:')} {chalk.value('assets/iphone-intake.txt')}")

    from telelink.outtake_share import (
        github_settings,
        outtake_auto_delete_poll_seconds,
        outtake_auto_delete_seconds,
    )

    ot = config.get("outtake", {}) or {}
    gh = github_settings(config)
    ot_ttl = outtake_auto_delete_seconds(config)
    if gh.get("owner") and gh.get("repo"):
        dest = f"{gh['owner']}/{gh['repo']}"
        if ot_ttl:
            poll_label = format_duration(int(outtake_auto_delete_poll_seconds(config)))
            _safe_print(
                f"\n{chalk.label('Outtake (GitHub)')}: {chalk.value(dest)} "
                f"auto-delete {chalk.value(format_duration(ot_ttl))} "
                f"(poll {chalk.value(poll_label)})"
            )
        else:
            _safe_print(
                f"\n{chalk.label('Outtake (GitHub)')}: {chalk.value(dest)} "
                f"{chalk.value('no auto-delete')}"
            )

    from telelink.airdrop_send import print_airdrop_status

    _safe_print("")
    print_airdrop_status(config)

    _safe_print(f"\n{chalk.muted('Run:')} {pretty.command('watcher')}")

    return 0


def dispatch_config_command(rest: list[str]) -> int:
    """Shell routing for tokens after ``config`` (edit/get/list never open the status view)."""
    sub = rest[0].lower() if rest else ""
    if not rest or sub in ("doctor", "check"):
        return cmd_config_show(Namespace())
    if sub == "edit":
        if len(rest) < 3:
            pretty.warn("usage: config edit <key> <value>")
            pretty.info("CONFIG", "list keys: config list")
            return 1
        return cmd_config_edit(Namespace(key=rest[1], value=rest[2:]))
    if sub == "get":
        if len(rest) < 2:
            pretty.warn("usage: config get <key>")
            return 1
        return cmd_config_get(Namespace(key=rest[1]))
    if sub in ("list", "ls"):
        return cmd_config_list(Namespace())
    if sub == "reset":
        ns = Namespace(yes=False)
        if len(rest) > 1 and rest[1] in ("-y", "--yes"):
            ns.yes = True
        return cmd_config_reset(ns)
    pretty.warn(f"unknown config command: {sub!r}")
    pretty.info("CONFIG", "config · config edit · config get · config list · config reset")
    return 1


def cmd_config(args: argparse.Namespace) -> int:
    action = getattr(args, "config_action", None)
    if action == "edit":
        return cmd_config_edit(args)
    if action == "get":
        return cmd_config_get(args)
    if action == "list":
        return cmd_config_list(args)
    if action == "reset":
        return cmd_config_reset(args)
    return cmd_config_show(args)


def main() -> None:
    from telelink.terminal import fix_stdio

    fix_stdio()
    if len(sys.argv) > 1 and sys.argv[1] == "tasks":
        sys.argv[1] = "caught"
    if len(sys.argv) > 1 and sys.argv[1] == "listen":
        sys.argv[1] = "watcher"
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.argv[1] = "config"
    if (
        len(sys.argv) >= 4
        and sys.argv[1] == "calendar"
        and sys.argv[-1].lower() == "status"
        and sys.argv[2].lower()
        not in {
            "list",
            "add",
            "delete",
            "delay",
            "status",
            "sync",
            "connect",
            "event-status",
            "cancel",
            "all",
            "help",
        }
    ):
        name = " ".join(sys.argv[2:-1])
        sys.argv = [sys.argv[0], "calendar", "event-status", name]

    # No args -> interactive shell (start.bat lands here)

    if len(sys.argv) == 1:

        from telelink.console import run_shell



        raise SystemExit(run_shell())



    parser = argparse.ArgumentParser(

        prog="telelink",

        description="Phone Link -> caught notifications.",

    )

    parser.add_argument("--version", action="version", version=__version__)

    sub = parser.add_subparsers(dest="command", required=True)



    p_watcher = sub.add_parser("watcher", help="Notification watcher (start/stop); alias: listen")
    p_watcher.add_argument(
        "--foreground",
        action="store_true",
        help="Run watcher in this terminal (start only)",
    )
    watcher_sub = p_watcher.add_subparsers(dest="watcher_action")
    p_watcher_stop = watcher_sub.add_parser("stop", help="Force stop the watcher window")
    p_watcher_stop.set_defaults(func=cmd_watcher_stop, watcher_action="stop")
    p_watcher.set_defaults(func=cmd_watcher)

    p_caught = sub.add_parser("caught", help="Browse caught notifications")

    p_caught.add_argument("--json", action="store_true", help="Show all JSON fields in a table")

    p_caught.add_argument("--raw", action="store_true", help="Print raw JSON (for scripts)")

    p_caught.add_argument("--gron", action="store_true", help="Greppable gron format")

    p_caught.add_argument("--limit", type=int, default=None)

    p_caught.add_argument("--channel", default=None, help="Filter: imessage, instagram, ...")

    p_caught.add_argument("--contact", default=None, help="Filter by matched contact name")

    p_caught.add_argument("--client", default=None, help=argparse.SUPPRESS)

    p_caught.add_argument("--sender", default=None, help="Filter by sender substring")

    p_caught.add_argument("--kind", default=None, help="text, image, screenshot")

    p_caught.add_argument("--contacts-only", action="store_true", help="Only matched contacts")

    p_caught.add_argument("--clients-only", action="store_true", help=argparse.SUPPRESS)

    p_caught.add_argument(

        "--group",

        choices=["channel", "platform", "contact", "client", "sender", "kind"],

        default=None,

        help="Group output (channel = notification platform)",

    )


    p_caught.set_defaults(func=cmd_caught)


    p_sync = sub.add_parser("sync", help="Re-sync Phone Link + contacts from all sources")
    p_sync.add_argument("--caught", action="store_true", help="Also import phone senders from caught log")
    p_sync.set_defaults(func=cmd_sync)

    p_wipe = sub.add_parser(
        "wipe",
        help="Clear local data (caught, sent, contacts, attachments, db, …)",
    )
    p_wipe.add_argument(
        "target",
        nargs="+",
        help="Target(s): caught, calls, sent, contacts, localstorage, attachments, analyze, seen, db, all",
    )
    p_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_wipe.set_defaults(func=cmd_wipe)

    p_intake = sub.add_parser("intake", help="Intake server — LAN, global, or stop")
    p_intake.add_argument("--qr", action="store_true", help="Show QR code (skip menu)")
    p_intake.add_argument("--sms", action="store_true", help="Send link via SMS (skip menu)")
    p_intake.add_argument("--wait", action="store_true", help="Keep server open until Ctrl+C")
    intake_sub = p_intake.add_subparsers(dest="intake_action")
    p_intake_stop = intake_sub.add_parser("stop", help="Stop intake server and public tunnel")
    p_intake_stop.set_defaults(func=cmd_intake_stop, intake_action="stop")
    p_intake_global = intake_sub.add_parser(
        "global",
        help="Public URL via cloudflared/ngrok (internet, not just LAN)",
    )
    p_intake_global.add_argument("--qr", action="store_true", help="Show QR code (skip menu)")
    p_intake_global.add_argument("--sms", action="store_true", help="Send link via SMS (skip menu)")
    p_intake_global.add_argument("--wait", action="store_true", help="Keep server open until Ctrl+C")
    p_intake_global.set_defaults(func=cmd_intake, intake_action="global")
    p_intake.set_defaults(func=cmd_intake)

    p_outtake = sub.add_parser("outtake", help="QR for a URL or file(s) (GitHub share; multiple files zipped)")
    p_outtake.add_argument(
        "target",
        nargs="+",
        help="URL or file path(s); multiple files are zipped e.g. a.pdf b.png",
    )
    p_outtake.add_argument("--qr", action="store_true", help="Show QR code (skip menu)")
    p_outtake.add_argument("--sms", action="store_true", help="Text link via SMS (skip menu)")
    p_outtake.add_argument(
        "--airdrop",
        action="store_true",
        help="Send local file(s) via AirDrop (OpenDrop) instead of GitHub",
    )
    p_outtake.set_defaults(func=cmd_outtake)

    p_airdrop = sub.add_parser(
        "airdrop",
        help="AirDrop to iPhone — list receivers or send a file (OpenDrop)",
    )
    p_airdrop.add_argument(
        "target",
        nargs="*",
        help='No args: list receivers. Or: "Receiver Name" <file|url> [files…]',
    )
    p_airdrop.add_argument(
        "--timeout",
        type=int,
        default=None,
        dest="find_timeout",
        help="Discovery scan seconds (default from config)",
    )
    p_airdrop.set_defaults(func=cmd_airdrop)



    p_config = sub.add_parser("config", help="Show or edit config.yaml; alias: doctor")
    config_sub = p_config.add_subparsers(dest="config_action")
    p_config_edit = config_sub.add_parser("edit", help="Set a config value (auto-saves config.yaml)")
    p_config_edit.add_argument("key", help="Key or alias (e.g. business, intake.port)")
    p_config_edit.add_argument("value", nargs="+", help="New value (quote strings with spaces)")
    p_config_edit.set_defaults(func=cmd_config, config_action="edit")
    p_config_get = config_sub.add_parser("get", help="Print one config value")
    p_config_get.add_argument("key", help="Key or alias")
    p_config_get.set_defaults(func=cmd_config, config_action="get")
    p_config_list = config_sub.add_parser("list", help="List all config keys and values")
    p_config_list.set_defaults(func=cmd_config, config_action="list")
    p_config_reset = config_sub.add_parser(
        "reset",
        help="Replace config.yaml with config.example.yaml",
    )
    p_config_reset.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_config_reset.set_defaults(func=cmd_config, config_action="reset")
    p_config.set_defaults(func=cmd_config, config_action=None)

    p_agent = sub.add_parser(
        "agent",
        help="AI agent cheat sheet and JSON context (read AGENTS.md)",
    )
    agent_sub = p_agent.add_subparsers(dest="agent_action")
    p_agent_guide = agent_sub.add_parser("guide", help="Print AGENTS.md cheat sheet (default)")
    p_agent_guide.set_defaults(func=cmd_agent, agent_action="guide")
    p_agent_context = agent_sub.add_parser(
        "context",
        help="JSON: owner tone, recent caught, analyze paths, exact commands",
    )
    p_agent_context.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Recent caught rows to include (default 5)",
    )
    p_agent_context.set_defaults(func=cmd_agent, agent_action="context")
    p_agent.set_defaults(func=cmd_agent, agent_action="guide")

    p_how = sub.add_parser("how", help="How-to guide for using TeleLink")
    p_how.add_argument(
        "topic",
        nargs="*",
        help="Optional topic (e.g. watcher, intake, config list)",
    )
    p_how.set_defaults(func=cmd_how)

    p_ars = sub.add_parser("ars", help="Auto-reply session controls")
    ars_sub = p_ars.add_subparsers(dest="ars_action")
    
    p_ars_start = ars_sub.add_parser("start", help="Start ARS session in a new window")
    p_ars_start.add_argument("session", help="Session slug (e.g. client-ars)")
    p_ars_start.add_argument("contact", nargs="+", help="Contact query or phone number")
    p_ars_start.add_argument("--max-turns", type=int, default=0, help="Stop after N replies")
    p_ars_start.add_argument("--idle", action="store_true", help="Start paused/idle")
    p_ars_start.add_argument("--no-bootstrap-reply", action="store_true", help="Start waiting even if thread needs reply")
    p_ars_start.add_argument("--force", action="store_true", help="Force recreate session")
    p_ars_start.set_defaults(func=cmd_ars, ars_action="start")
    
    p_ars_stop = ars_sub.add_parser("stop", help="Stop one ARS session or all sessions")
    p_ars_stop.add_argument("session", nargs="?", default=None, help="Session slug (optional)")
    p_ars_stop.set_defaults(func=cmd_ars, ars_action="stop")
    
    p_ars_status = ars_sub.add_parser("status", help="Show one ARS session status")
    p_ars_status.add_argument("session", help="Session slug")
    p_ars_status.add_argument("--raw", action="store_true", help="Print raw JSON")
    p_ars_status.set_defaults(func=cmd_ars, ars_action="status")
    
    p_ars_list = ars_sub.add_parser("list", help="List ARS sessions")
    p_ars_list.add_argument("--raw", action="store_true", help="Print raw JSON")
    p_ars_list.set_defaults(func=cmd_ars, ars_action="list")
    
    p_ars_next = ars_sub.add_parser("next", help="Run one ARS tick and print next action")
    p_ars_next.add_argument("session", help="Session slug")
    p_ars_next.add_argument("--raw", action="store_true", help="Print raw JSON")
    p_ars_next.set_defaults(func=cmd_ars, ars_action="next")
    
    p_ars_tick = ars_sub.add_parser("tick", help="Run one ARS tick")
    p_ars_tick.add_argument("session", help="Session slug")
    p_ars_tick.add_argument("--raw", action="store_true", help="Print raw JSON")
    p_ars_tick.set_defaults(func=cmd_ars, ars_action="tick")
    
    p_ars_run = ars_sub.add_parser("run", help="Run ARS loop (foreground)")
    p_ars_run.add_argument("session", help="Session slug")
    p_ars_run.add_argument("contact", nargs="+", help="Contact query or phone number")
    p_ars_run.add_argument("--foreground", action="store_true", help="Run in current terminal")
    p_ars_run.set_defaults(func=cmd_ars, ars_action="run")
    
    p_ars_ack = ars_sub.add_parser("ack", help="Agent turn complete")
    p_ars_ack.add_argument("session", help="Session slug")
    p_ars_ack.add_argument("--force", action="store_true", help="Force ack (manual send on phone)")
    p_ars_ack.set_defaults(func=cmd_ars, ars_action="ack")
    
    p_ars_pause = ars_sub.add_parser("pause", help="Pause ARS poll loop")
    p_ars_pause.add_argument("session", help="Session slug")
    p_ars_pause.set_defaults(func=cmd_ars, ars_action="pause")
    
    p_ars_resume = ars_sub.add_parser("resume", help="Resume paused ARS session")
    p_ars_resume.add_argument("session", help="Session slug")
    p_ars_resume.set_defaults(func=cmd_ars, ars_action="resume")
    
    p_ars_wait = ars_sub.add_parser("wait", help="Block until reply needed or stopped")
    p_ars_wait.add_argument("session", help="Session slug")
    p_ars_wait.add_argument("--raw", action="store_true", help="Print raw JSON")
    p_ars_wait.add_argument("--timeout", default=None, help="Max wait duration")
    p_ars_wait.set_defaults(func=cmd_ars, ars_action="wait")
    
    p_ars_delete = ars_sub.add_parser("delete", help="Remove session files")
    p_ars_delete.add_argument("session_list", nargs="+", help="Session slugs")
    p_ars_delete.set_defaults(func=cmd_ars, ars_action="delete")

    p_contacts = sub.add_parser("contacts", help="Manage contacts (name → phone, match rules)")

    p_contacts.add_argument("--search", "-q", default=None, help="Filter by name/phone")

    p_contacts.add_argument("--sync-config", action="store_true", help="Import from legacy config clients list")

    p_contacts.add_argument("--sync-caught", action="store_true", help="Import phone-like senders from caught log")
    p_contacts.add_argument("--sync-tasks", action="store_true", help=argparse.SUPPRESS)

    p_contacts.add_argument("--add", dest="add_name", metavar="NAME", help="Add or update a contact")

    p_contacts.add_argument("--phone", default="", help="Phone for --add")

    p_contacts.add_argument("--match", default="", help="Comma-separated match patterns for --add")

    p_contacts.add_argument("--platform", default="", help="Default platform label (imessage, sms, ...)")

    p_contacts.add_argument("--personal", action="store_true", help="Personal contact (no notification matching)")

    p_contacts.add_argument("--notes", default="", help="Notes for --add")

    p_contacts.add_argument("--remove", metavar="NAME", help="Remove contact by name")

    p_contacts.set_defaults(func=cmd_contacts)



    p_send = sub.add_parser(
        "send",
        help="Send SMS now, or schedule: send in%%<when>%% <who> <msg>",
    )

    p_send.add_argument(
        "payload",
        nargs=argparse.REMAINDER,
        help="send <who> <msg>  or  send in%%2hour%% <who> <msg>",
    )

    p_send.set_defaults(func=cmd_send)

    p_calendar = sub.add_parser(
        "calendar",
        help="Schedule SMS and view events (optional Google Calendar sync)",
    )
    calendar_sub = p_calendar.add_subparsers(dest="calendar_action")
    p_cal_list = calendar_sub.add_parser("list", help="List scheduled events")
    p_cal_list.add_argument("--all", action="store_true", help="Include completed/cancelled")
    p_cal_list.set_defaults(func=cmd_calendar, calendar_action="list")
    p_cal_add = calendar_sub.add_parser("add", help="Schedule a message")
    p_cal_add.add_argument("name", help="Event name (slug for calendar delay/delete)")
    p_cal_add.add_argument("to", help="Contact name or +number")
    p_cal_add.add_argument("when", help='When to send — e.g. "2pm today", "in 3h"')
    p_cal_add.add_argument("message", nargs="+", help="Message body")
    p_cal_add.set_defaults(func=cmd_calendar, calendar_action="add")
    p_cal_delete = calendar_sub.add_parser("delete", help="Delete a scheduled event")
    p_cal_delete.add_argument("name", help="Event name")
    p_cal_delete.set_defaults(func=cmd_calendar, calendar_action="delete")
    p_cal_delay = calendar_sub.add_parser("delay", help="Postpone an event")
    p_cal_delay.add_argument("name", help="Event name")
    p_cal_delay.add_argument("when", help="New time — in 1h, 2pm tomorrow, …")
    p_cal_delay.set_defaults(func=cmd_calendar, calendar_action="delay")
    p_cal_cancel = calendar_sub.add_parser("cancel", help="Cancel a scheduled event (keep in history)")
    p_cal_cancel.add_argument("name", help="Event name")
    p_cal_cancel.set_defaults(func=cmd_calendar, calendar_action="cancel")
    p_cal_event = calendar_sub.add_parser("event-status", help="Status for one scheduled event")
    p_cal_event.add_argument("name", help="Event name")
    p_cal_event.set_defaults(func=cmd_calendar, calendar_action="event_status")
    p_cal_status = calendar_sub.add_parser("status", help="Calendar + Google sync status")
    p_cal_status.set_defaults(func=cmd_calendar, calendar_action="status")
    p_cal_sync = calendar_sub.add_parser("sync", help="Force Google Calendar sync")
    p_cal_sync.set_defaults(func=cmd_calendar, calendar_action="sync")
    p_cal_connect = calendar_sub.add_parser("connect", help="Connect external calendar")
    p_cal_connect_sub = p_cal_connect.add_subparsers(dest="connect_target")
    p_cal_google = p_cal_connect_sub.add_parser("google", help="OAuth connect to Google Calendar")
    p_cal_google.set_defaults(func=cmd_calendar, calendar_action="connect", rest=["google"])
    p_calendar.set_defaults(func=cmd_calendar, calendar_action="list")

    p_calls = sub.add_parser("calls", help="Recent calls from Phone Link (default TTL: calls.ttl / 1d)")
    p_calls.add_argument("--limit", type=int, default=None, help="Max rows to show")
    calls_sub = p_calls.add_subparsers(dest="calls_action")
    p_calls_sync = calls_sub.add_parser(
        "sync",
        help="Import call history from Phone Link calling.db",
    )
    p_calls_sync.set_defaults(func=cmd_calls, calls_action="sync")
    p_calls.set_defaults(func=cmd_calls)

    p_missed = sub.add_parser("missed", help="Missed calls table (same TTL as calls log)")
    p_missed.add_argument("--limit", type=int, default=None, help="Max rows to show")
    p_missed.set_defaults(func=cmd_missed)

    p_convo = sub.add_parser(
        "convo",
        help="Phone Link message history (phone.db) for a contact or number",
    )
    p_convo.add_argument("--json", action="store_true", help="Table with source column")
    p_convo.add_argument("--raw", action="store_true", help="One JSON object per line")
    p_convo.add_argument(
        "rest",
        nargs="*",
        default=[],
        help="convo mom · convo last 5 mom · convo today +1… · convo threads",
    )
    p_convo.set_defaults(func=cmd_convo)

    p_received = sub.add_parser(
        "received",
        help="Incoming SMS from a contact (full text, JSON for agents)",
    )
    p_received.add_argument(
        "rest",
        nargs="*",
        default=[],
        help="received mom · received last 5 mom · received +15551234567",
    )
    p_received.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max incoming messages (default 20, or from 'last N')",
    )
    p_received.set_defaults(func=cmd_received)


    p_zns = sub.add_parser(
        "zns",
        help="ZeroNoShow bridge: send ZeroNoShow SMS from the iPhone (zns run · once · status)",
    )
    p_zns.add_argument(
        "zns_action",
        nargs="?",
        default="status",
        choices=["run", "once", "status"],
        help="run = loop · once = one pass · status = check config/server",
    )
    p_zns.set_defaults(func=cmd_zns)

    p_shell = sub.add_parser("shell", help="Interactive CLI")

    p_shell.set_defaults(func=cmd_shell)



    args = parser.parse_args()

    try:

        raise SystemExit(args.func(args))

    except KeyboardInterrupt:

        raise SystemExit(0) from None

    except FileNotFoundError as exc:

        print(exc, file=sys.stderr)

        raise SystemExit(1) from exc





if __name__ == "__main__":

    main()

