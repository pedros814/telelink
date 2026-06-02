"""CLI — calls and missed commands."""

from __future__ import annotations

from argparse import Namespace

from telelink import pretty
from telelink.call_log import CallLogStore, call_log_enabled
from telelink.ora import ora
from telelink.session import get_session
from telelink.table import calls_table


def _store() -> CallLogStore:
    return get_session().call_log_store


def cmd_calls(args: Namespace) -> int:
    if not call_log_enabled(get_session().config_fresh()):
        pretty.warn("call log is disabled — config edit calls_enabled true")
        return 1

    limit = getattr(args, "limit", None)
    with ora("Loading call log", kind="load"):
        rows = _store().list_calls(limit=limit)

    title = "Recent calls"
    if limit:
        title = f"Recent calls (last {limit})"
    print(calls_table(rows, title=title))
    if not rows:
        pretty.info(
            "CALLS",
            "no calls in log — run sync or calls sync to import from Phone Link calling.db",
        )
    return 0


def cmd_calls_sync(_args: Namespace) -> int:
    from telelink.phone_link_calls import resolve_calling_db_path, sync_calls_from_phone_link

    config = get_session().config_fresh()
    if not call_log_enabled(config):
        pretty.warn("call log is disabled — config edit calls_enabled true")
        return 1

    db = resolve_calling_db_path(config)
    if not db:
        pretty.warn(
            "Phone Link calling.db not found — open Phone Link, go to Calls, "
            "and let it sync from your iPhone"
        )
        return 1

    with ora("Importing calls from Phone Link", kind="load"):
        n = sync_calls_from_phone_link(
            config,
            _store(),
            contact_store=get_session().contact_store,
        )

    pretty.info("CALLS", f"imported {n} new call(s) from {db.name}")
    return 0


def cmd_missed(args: Namespace) -> int:
    if not call_log_enabled(get_session().config_fresh()):
        pretty.warn("call log is disabled — config edit calls_enabled true")
        return 1

    limit = getattr(args, "limit", None)
    with ora("Loading missed calls", kind="load"):
        rows = _store().list_calls(kind="missed", limit=limit)

    print(calls_table(rows, title="Missed calls"))
    if not rows:
        pretty.info(
            "CALLS",
            "no missed calls in log — try calls sync, or config edit calls_ttl 7d for older history",
        )
    return 0
