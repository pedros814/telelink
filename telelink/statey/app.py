"""TeleLink screens wired through Statey."""

from __future__ import annotations

import os
import shlex
import sys
from argparse import Namespace
from pathlib import Path

from telelink import __version__, chalk, pretty
from telelink.cli import (
    cmd_config,
    dispatch_config_command,
    cmd_contacts,
    cmd_intake,
    cmd_intake_stop,
    cmd_outtake,
    cmd_calls,
    cmd_caught,
    cmd_missed,
    cmd_sync,
    cmd_watcher_stop,
    cmd_wipe,
)
from telelink.statey.engine import Statey
from telelink.statey.types import FlowStep, HandleResult, NavAction, Screen
from telelink.statey import ui

ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS = ROOT / "assets"

_ROOT_HELP = [
    "watcher         start notification watcher (new window)",
    "watcher stop    force stop watcher window",
    "caught          browse caught notifications",
    "contacts        contacts table (name → phone)",
    "send <who> msg  text now (Phone Link)",
    "send in1m <who> msg  schedule SMS (in1m, in%2hour%, in%2pm today%)",
    "config          show config, paths, and contacts",
    'config edit <key> <value>  — change config.yaml (e.g. config edit business "Your Business")',
    "config list     all keys · config get <key>",
    "config reset    restore config.yaml from config.example.yaml",
    "how             full how-to guide (read this first)",
    "how <topic>     topic guide (e.g. how watcher, how intake)",
    "intake          LAN share — QR or text the link",
    "intake global   public URL (internet, not just LAN)",
    "intake stop     stop intake server",
    "outtake <url|file…>  QR — link or GitHub file share (multi-file → zip)",
    "calendar        scheduled events table",
    "calendar add …  schedule SMS for later",
    "calendar status calendar + Google sync health",
    "sync            re-sync Phone Link + contacts (auto every 15m)",
    "calls           recent calls (Phone Link toasts, 1d log)",
    "missed          missed calls table",
    "convo <who>     SMS thread from Phone Link (mom, +number, last 5, today)",
    "convo threads   list recent Phone Link conversations",
    "ars             manage auto-reply sessions (start, stop, list, status)",
    "status          quick summary",
    "wipe <target>   clear local data (wipe all --yes)",
    "help <topic>    detailed how-to (e.g. help watcher, help config list)",
]

_CONTACTS_HELP = [
    "contacts add Name +15551234567  — save a contact",
    "contacts sync                 — import from config.yaml",
    "send \"Name\" your message here   — opens SMS compose",
    "back · cancel · help",
]

_CAUGHT_HELP = [
    "Pick a number or type: caught contacts, caught last 5, caught json, caught group channel.",
    "back · cancel · help",
]

def _say(text: str = "") -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(chalk.strip(text).encode(enc, errors="replace").decode(enc), flush=True)


_CAUGHT_FLAGS = frozenset(
    {"json", "raw", "gron", "contacts", "clients", "last", "group", "all", "caught", "tasks"}
)


def _parse_caught_args(parts: list[str]) -> Namespace:
    ns = Namespace(
        json=False,
        raw=False,
        gron=False,
        limit=None,
        channel=None,
        contact=None,
        sender=None,
        kind=None,
        contacts_only=False,
        clients_only=False,
        group=None,
    )
    title_parts: list[str] = []
    i = 0
    while i < len(parts):
        p = parts[i].lower()
        if p == "json":
            ns.json = True
        elif p == "raw":
            ns.raw = True
        elif p == "gron":
            ns.gron = True
        elif p in ("contacts", "clients"):
            ns.contacts_only = True
        elif p.startswith("contact:"):
            ns.contact = p.split(":", 1)[1]
        elif p == "last" and i + 1 < len(parts) and parts[i + 1].isdigit():
            ns.limit = int(parts[i + 1])
            i += 1
        elif p == "group" and i + 1 < len(parts):
            g = parts[i + 1].lower()
            if g in ("channel", "platform", "contact", "client", "sender", "kind"):
                ns.group = "contact" if g == "client" else g
            i += 1
        elif p.startswith("channel:"):
            ns.channel = p.split(":", 1)[1]
        elif p.startswith("kind:"):
            ns.kind = p.split(":", 1)[1]
        i += 1
    return ns


def _run_caught(ns: Namespace) -> None:
    try:
        cmd_caught(ns)
    except Exception as exc:
        pretty.warn(str(exc))
    _say()


def _run_send_line(text: str) -> None:
    from telelink.send_parse import parse_send_line, run_send_intent

    try:
        intent = parse_send_line(text)
    except ValueError as exc:
        pretty.warn(str(exc))
        _say()
        return
    try:
        run_send_intent(intent)
    except Exception as exc:
        pretty.warn(str(exc))
    _say()


def _run_contacts(ns: Namespace) -> None:
    try:
        cmd_contacts(ns)
    except Exception as exc:
        pretty.warn(str(exc))
    _say()


def _cmd_status(statey: Statey) -> None:
    from telelink.ora import ora
    from telelink.table import status_table

    with ora("Loading caught", kind="load"):
        config = statey.config()
        rows = statey.store().list_caught()
    from telelink.task_rows import task_matched

    matched = sum(1 for r in rows if task_matched(r))
    by_ch: dict[str, int] = {}
    for r in rows:
        ch = r.get("channel") or "unknown"
        by_ch[ch] = by_ch.get(ch, 0) + 1

    _say(
        status_table(
            total=len(rows),
            matched=matched,
            channels=by_ch,
            caught_file=str(config["output"]["caught_file"]),
            attachments_dir=str(config["output"]["attachments_dir"]),
        )
    )
    _say()


def _show_help() -> None:
    from telelink.table import help_table

    _say(help_table())


def _show_help_topic(parts: list[str]) -> None:
    from telelink.how_guide import display_help_topic

    display_help_topic(parts)


def _show_banner(preloaded: str | None = None) -> None:
    from telelink import ink_ui
    from telelink.console import load_banner
    from telelink.splash import load_text_art

    os.system("cls" if sys.platform == "win32" else "clear")
    _say(
        ink_ui.boot_screen(
            preloaded if preloaded is not None else load_banner(),
            side_art=load_text_art(),
        )
    )
    _say()


def _on_caught_enter(statey: Statey) -> None:
    ui.menu(
        "caught",
        [
            ("1", "all caught"),
            ("2", "matched contacts only"),
            ("3", "last 5"),
            ("4", "json view"),
            ("5", "gron view"),
            ("6", "group by channel"),
            ("7", "custom filter flow"),
        ],
    )


def _handle_caught(statey: Statey, line: str) -> HandleResult | None:
    parts = line.split()
    cmd = parts[0].lower() if parts else ""
    rest = parts[1:]

    if cmd.isdigit():
        choice = int(cmd)
        mapping = {
            1: Namespace(),
            2: Namespace(contacts_only=True),
            3: Namespace(limit=5),
            4: Namespace(json=True),
            5: Namespace(gron=True),
            6: Namespace(group="channel"),
        }
        if choice in mapping:
            _run_caught(mapping[choice])
            return HandleResult()
        if choice == 7:
            statey.start_flow(
                "filter",
                [
                    FlowStep("view", "Output format", kind="select", choices=["table", "json", "gron"], initial=0),
                    FlowStep("scope", "Scope", kind="select", choices=["all", "matched contacts only", "last 5"], initial=0),
                    FlowStep(
                        "channel",
                        "Channel filter (blank = any)",
                        kind="text",
                        initial="",
                    ),
                ],
            )
            statey.show_flow_prompt()
            return HandleResult()

    if cmd == "caught" or cmd in ("all", "contacts", "clients", "json", "gron", "raw"):
        _run_caught(_parse_caught_args(parts if cmd != "caught" else rest))
        return HandleResult()

    if rest or cmd not in ("caught",):
        _run_caught(_parse_caught_args(parts))
        return HandleResult()

    pretty.warn("pick 1-7 or type a caught command")
    return HandleResult()


def _on_contacts_enter(statey: Statey) -> None:
    ui.menu(
        "contacts",
        [
            ("1", "show contacts table"),
            ("2", "sync from config.yaml"),
            ("3", "sync from caught"),
            ("4", "add contact (guided)"),
            ("5", "send message (guided)"),
        ],
    )


def _contacts_menu_action(line: str) -> int | None:
    """Map menu label text (not just digits) to contacts submenu actions."""
    t = (line or "").strip().lower()
    if not t:
        return None
    if t.isdigit():
        n = int(t)
        return n if 1 <= n <= 5 else None
    if t in ("show", "list", "table") or t.startswith("show contact"):
        return 1
    if t == "sync" or t.startswith("sync from config") or t in ("sync config", "sync-config"):
        return 2
    if t in ("sync-caught", "sync caught") or t.startswith("sync from caught"):
        return 3
    if t.startswith("add contact") or t == "add":
        return 4
    if t.startswith("send message") or t == "send":
        return 5
    return None


def _run_contacts_menu_action(statey: Statey, choice: int) -> HandleResult:
    if choice == 1:
        _run_contacts(Namespace())
        return HandleResult()
    if choice == 2:
        _run_contacts(Namespace(sync_config=True))
        return HandleResult()
    if choice == 3:
        _run_contacts(Namespace(sync_caught=True))
        return HandleResult()
    if choice == 4:
        statey.start_flow(
            "contact_add",
            [
                FlowStep("name", "Contact name"),
                FlowStep("phone", "Phone number (+1...)"),
                FlowStep("match", "Match patterns (comma-separated, optional)", initial=""),
                FlowStep("platform", "Platform label (optional, e.g. imessage)", initial=""),
            ],
        )
        statey.show_flow_prompt()
        return HandleResult()
    if choice == 5:
        statey.start_flow(
            "send",
            [
                FlowStep("to", "Contact name or phone number"),
                FlowStep("message", "Message to send"),
                FlowStep("confirm", "Open SMS compose?", kind="confirm", initial=True),
            ],
        )
        statey.show_flow_prompt()
        return HandleResult()
    pretty.warn("pick 1-5 or: contacts add Name +1234567890")
    return HandleResult()


def _handle_contacts(statey: Statey, line: str) -> HandleResult | None:
    parts = line.split()
    cmd = parts[0].lower() if parts else ""
    rest = parts[1:]

    menu_action = _contacts_menu_action(line)
    if menu_action is not None:
        return _run_contacts_menu_action(statey, menu_action)

    if cmd == "contacts":
        if not rest:
            _run_contacts(Namespace())
            return HandleResult()
        sub = rest[0].lower()
        if sub == "sync":
            _run_contacts(Namespace(sync_config=True))
            return HandleResult()
        if sub == "sync-caught":
            _run_contacts(Namespace(sync_caught=True))
            return HandleResult()
        if sub == "add" and len(rest) >= 3:
            _run_contacts(
                Namespace(
                    add_name=rest[1],
                    phone=rest[2],
                    match=rest[3] if len(rest) > 3 else "",
                )
            )
            return HandleResult()
        if sub == "remove" and len(rest) >= 2:
            _run_contacts(Namespace(remove=rest[1]))
            return HandleResult()
        if sub == "add":
            statey.start_flow(
                "contact_add",
                [
                    FlowStep("name", "Contact name"),
                    FlowStep("phone", "Phone number (+1...)"),
                    FlowStep("match", "Match patterns (comma-separated, optional)", initial=""),
                    FlowStep("platform", "Platform label (optional)", initial=""),
                ],
            )
            statey.show_flow_prompt()
            return HandleResult()

    if cmd == "add" and len(rest) >= 2:
        name = rest[0]
        phone = rest[1]
        match = rest[2] if len(rest) > 2 else ""
        _run_contacts(Namespace(add_name=name, phone=phone, match=match))
        return HandleResult()

    if cmd in ("send", "msg", "text", "sms"):
        if not rest:
            statey.start_flow(
                "send",
                [
                    FlowStep("to", "Contact name or phone number"),
                    FlowStep("message", "Message to send"),
                    FlowStep("confirm", "Open SMS compose?", kind="confirm", initial=True),
                ],
            )
            statey.show_flow_prompt()
            return HandleResult()
        _run_send_line(" ".join(rest))
        return HandleResult()

    if cmd == "convo":
        from telelink.convo import dispatch_convo_command

        dispatch_convo_command(rest)
        _say()
        return HandleResult()

    if cmd == "contacts" and rest:
        _run_contacts(Namespace(search=" ".join(rest)))
        return HandleResult()

    if cmd not in ("contacts", "add", "remove", "sync", "sync-caught") and line.strip():
        _run_contacts(Namespace(search=line.strip()))
        return HandleResult()

    pretty.warn("pick 1-5 or: contacts add Name +1234567890")
    return HandleResult()


def _handle_root(statey: Statey, line: str) -> HandleResult | None:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        pretty.warn(str(exc))
        return HandleResult()
    if not parts:
        return HandleResult()
    cmd = parts[0].lower()
    rest = parts[1:]

    if cmd in ("help", "?"):
        if rest:
            _show_help_topic(rest)
        else:
            _show_help()
        return HandleResult()

    if cmd in ("clear", "cls", "cc"):
        _show_banner()
        return HandleResult()

    if cmd == "status":
        _cmd_status(statey)
        return HandleResult()

    if cmd in ("config", "doctor", "check"):
        if cmd in ("doctor", "check"):
            cmd_config(Namespace())
        else:
            dispatch_config_command(rest)
        _say()
        return HandleResult()

    if cmd == "how":
        from telelink.how_guide import display_help_topic, render_how_guide

        if rest:
            display_help_topic(rest)
        else:
            _say(render_how_guide())
        _say()
        return HandleResult()

    if cmd == "runreminderalert":
        from telelink.intake_remind import emit_intake_running_reminder

        emit_intake_running_reminder(statey.config(), force=True)
        _say()
        return HandleResult()

    if cmd == "runcalendarreminder":
        from telelink.calendar_remind import emit_calendar_pending_reminder

        emit_calendar_pending_reminder(statey.config(), force=True)
        _say()
        return HandleResult()

    if cmd == "runcallsreminder":
        from telelink.calls_remind import emit_missed_calls_reminder

        emit_missed_calls_reminder(statey.config(), force=True)
        _say()
        return HandleResult()

    if cmd == "calls":
        if rest and rest[0].lower() == "sync":
            from telelink.calls import cmd_calls_sync

            cmd_calls_sync(Namespace())
        else:
            cmd_calls(Namespace(limit=int(rest[0]) if rest and rest[0].isdigit() else None))
        _say()
        return HandleResult()

    if cmd == "missed":
        cmd_missed(Namespace(limit=int(rest[0]) if rest and rest[0].isdigit() else None))
        _say()
        return HandleResult()

    if cmd == "convo":
        from telelink.convo import dispatch_convo_command

        dispatch_convo_command(rest)
        _say()
        return HandleResult()

    if cmd == "calendar":
        from telelink.calendar import dispatch_calendar_command

        dispatch_calendar_command(rest)
        _say()
        return HandleResult()

    if cmd == "sync":
        ns = Namespace(caught="--caught" in rest or "caught" in rest)
        cmd_sync(ns)
        _say()
        return HandleResult()

    if cmd == "intake":
        if rest and rest[0].lower() == "stop":
            cmd_intake_stop(Namespace())
            _say()
            return HandleResult()
        if rest and rest[0].lower() == "global":
            ns = Namespace()
            ns.intake_action = "global"
            if len(rest) > 1 and rest[1].lower() in ("--qr", "qr"):
                ns.qr = True
            cmd_intake(ns)
            _say()
            return HandleResult()
        cmd_intake(Namespace())
        _say()
        return HandleResult()

    if cmd == "outtake":
        if not rest:
            pretty.warn("usage: outtake <url>  or  outtake <file> [file ...]")
            return HandleResult()
        ns = Namespace(target=list(rest))
        flags = {t.lower().lstrip("-") for t in rest}
        if flags & {"qr"}:
            ns.qr = True
        if flags & {"sms", "text", "message", "msg"}:
            ns.sms = True
        if getattr(ns, "qr", False) or getattr(ns, "sms", False):
            skip = {"qr", "sms", "text", "message", "msg", "--qr", "--sms"}
            ns.target = [t for t in rest if t.lower().lstrip("-") not in skip]
        cmd_outtake(ns)
        _say()
        return HandleResult()

    if cmd == "auto":
        p = ASSETS / "ios-auto-intake.txt"
        _say(p.read_text(encoding="utf-8") if p.exists() else "See assets/ios-auto-intake.txt")
        return HandleResult()

    if cmd in ("watcher", "listen", "start"):
        if rest and rest[0].lower() == "stop":
            cmd_watcher_stop(Namespace())
            _say()
            return HandleResult()
        from telelink.listener_spawn import is_watcher_running, spawn_watcher_window

        if spawn_watcher_window(root=ROOT, background=True):
            pretty.info("WATCHER", "started in background (minimized)")
        elif is_watcher_running():
            pretty.info("WATCHER", "already running in its window")
        else:
            pretty.warn("could not start watcher")
        _say()
        return HandleResult()

    if cmd in ("stop", "watcher-stop", "listen-stop"):
        cmd_watcher_stop(Namespace())
        _say()
        return HandleResult()

    if cmd == "caught":
        if rest:
            _run_caught(_parse_caught_args(rest))
            return HandleResult()
        return HandleResult(NavAction.PUSH, target="caught")

    if cmd in ("send", "msg", "text", "sms"):
        if not rest:
            statey.start_flow(
                "send",
                [
                    FlowStep("to", "Contact name or phone number"),
                    FlowStep("message", "Message to send"),
                    FlowStep("confirm", "Open SMS compose?", kind="confirm", initial=True),
                ],
            )
            statey.show_flow_prompt()
            return HandleResult()
        _run_send_line(" ".join(rest))
        return HandleResult()

    if cmd == "contacts":
        if rest:
            return _handle_contacts(statey, line)
        return HandleResult(NavAction.PUSH, target="contacts")

    if cmd == "wipe":
        if not rest:
            pretty.warn("usage: wipe <target> [target …]  —  wipe all  ·  wipe caught sent")
            return HandleResult()
        ns = Namespace(target=rest, yes=False)
        if rest and rest[-1] in ("-y", "--yes"):
            ns.yes = True
            ns.target = [t for t in rest if t not in ("-y", "--yes")]
        cmd_wipe(ns)
        _say()
        return HandleResult()

    if cmd == "ars":
        from telelink import ars_cli
        action = rest[0].lower() if rest else "list"
        ns = Namespace()
        
        # Simple string-based argument parsing for common flags
        raw = "--raw" in rest
        force = "--force" in rest
        idle = "--idle" in rest
        no_bootstrap = "--no-bootstrap-reply" in rest
        clean_args = [x for x in rest[1:] if not x.startswith("--")]
        
        if action == "start":
            if not clean_args:
                pretty.warn("usage: ars start <session> <contact>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.contact = clean_args[1:]
            ns.max_turns = 0
            for i, x in enumerate(rest):
                if x == "--max-turns" and i + 1 < len(rest):
                    ns.max_turns = int(rest[i+1])
            ns.idle = idle
            ns.no_bootstrap_reply = no_bootstrap
            ns.force = force
            ars_cli.cmd_ars_start(ns)
        elif action == "stop":
            ns.session = clean_args[0] if clean_args else None
            ars_cli.cmd_ars_stop(ns)
        elif action == "status":
            if not clean_args:
                pretty.warn("usage: ars status <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.raw = raw
            ars_cli.cmd_ars_status(ns)
        elif action == "list":
            ns.raw = raw
            ars_cli.cmd_ars_list(ns)
        elif action == "next":
            if not clean_args:
                pretty.warn("usage: ars next <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.raw = raw
            ars_cli.cmd_ars_next(ns)
        elif action == "tick":
            if not clean_args:
                pretty.warn("usage: ars tick <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.raw = raw
            ars_cli.cmd_ars_tick(ns)
        elif action == "run":
            if not clean_args:
                pretty.warn("usage: ars run <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.contact = clean_args[1:]
            ns.foreground = "--foreground" in rest
            ars_cli.cmd_ars_run(ns)
        elif action == "ack":
            if not clean_args:
                pretty.warn("usage: ars ack <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.force = force
            ars_cli.cmd_ars_ack(ns)
        elif action == "pause":
            if not clean_args:
                pretty.warn("usage: ars pause <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ars_cli.cmd_ars_pause(ns)
        elif action == "resume":
            if not clean_args:
                pretty.warn("usage: ars resume <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ars_cli.cmd_ars_resume(ns)
        elif action == "wait":
            if not clean_args:
                pretty.warn("usage: ars wait <session>")
                return HandleResult()
            ns.session = clean_args[0]
            ns.raw = raw
            ns.timeout = None
            for i, x in enumerate(rest):
                if x == "--timeout" and i + 1 < len(rest):
                    ns.timeout = rest[i+1]
            ars_cli.cmd_ars_wait(ns)
        elif action == "delete":
            if not clean_args:
                pretty.warn("usage: ars delete <session>")
                return HandleResult()
            from telelink.ars_store import delete_session, normalize_session_name
            for target in clean_args:
                delete_session(normalize_session_name(target))
        else:
            pretty.warn(f"unknown ars command: {action!r}")
            
        _say()
        return HandleResult()

    pretty.warn(f"unknown command — type {pretty.command('help')}")
    return HandleResult()


@Statey.on_flow("filter")
def _flow_filter(statey: Statey, data: dict) -> None:
    ns = Namespace()
    view = str(data.get("view") or "table")
    scope = str(data.get("scope") or "all")
    channel = str(data.get("channel") or "").strip()

    if view == "json":
        ns.json = True
    elif view == "gron":
        ns.gron = True

    if scope in ("clients only", "matched contacts only"):
        ns.contacts_only = True
    elif scope == "last 5":
        ns.limit = 5

    if channel:
        ns.channel = channel

    _run_caught(ns)


@Statey.on_flow("contact_add")
def _flow_contact_add(statey: Statey, data: dict) -> None:
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not name or not phone:
        pretty.warn("name and phone are required")
        return
    match_raw = str(data.get("match") or "").strip()
    _run_contacts(
        Namespace(
            add_name=name,
            phone=phone,
            match=match_raw,
            platform=str(data.get("platform") or ""),
        )
    )


@Statey.on_flow("send")
def _flow_send(statey: Statey, data: dict) -> None:
    if not data.get("confirm", True):
        pretty.warn("cancelled")
        return
    to = str(data.get("to") or "").strip()
    message = str(data.get("message") or "").strip()
    if not to or not message:
        pretty.warn("contact and message are required")
        return
    _run_send_line(f"{to} {message}")


def build_statey() -> Statey:
    statey = Statey()
    statey.register(
        Screen(
            id="root",
            title="telelink",
            handle=_handle_root,
            help_lines=_ROOT_HELP,
        )
    )
    statey.register(
        Screen(
            id="caught",
            title="caught",
            handle=_handle_caught,
            on_enter=_on_caught_enter,
            help_lines=_CAUGHT_HELP,
        )
    )
    statey.register(
        Screen(
            id="contacts",
            title="contacts",
            handle=_handle_contacts,
            on_enter=_on_contacts_enter,
            help_lines=_CONTACTS_HELP,
        )
    )
    return statey
