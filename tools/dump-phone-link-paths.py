#!/usr/bin/env python3
"""Dev script: Phone Link package roots, folder/DB discovery, and fallback status."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telelink.config import discover_phone_link_folders, load_config
from telelink.harvest import _pkg_roots, find_phone_link_databases
from telelink.phone_link_contacts import (
    describe_contacts_db_discovery,
    discover_contacts_databases,
)
from telelink.phone_link_fallback import fallback_status
from telelink.phone_link_messages import describe_phone_db_status, discover_phone_databases


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    config = load_config()

    _section("Package roots (_pkg_roots)")
    roots = _pkg_roots()
    if roots:
        for root in roots:
            print(f"  {root}")
    else:
        print("  (none)")

    _section("Watch folder candidates (discover_phone_link_folders)")
    folders = discover_phone_link_folders()
    if folders:
        for folder in folders:
            print(f"  {folder}")
    else:
        print("  (none)")

    _section("Configured watch_folders")
    for folder in (config.get("phone_link") or {}).get("watch_folders") or []:
        print(f"  {folder}")

    _section("contacts.db discovery")
    contacts = discover_contacts_databases(probe=True, config=config)
    for cand in contacts:
        flag = "valid" if cand.valid else "invalid"
        print(
            f"  [{flag}] {cand.path} "
            f"(contacts={cand.contact_rows}, phones={cand.phone_rows})"
        )
    pl_info = describe_contacts_db_discovery(config)
    print(f"  chosen: {pl_info.get('chosen') or '(none)'}")
    print(f"  discovery_method: {pl_info.get('discovery_method', 'none')}")

    _section("phone.db discovery")
    phone_paths = discover_phone_databases(config)
    for path in phone_paths:
        print(f"  {path}")
    phone_info = describe_phone_db_status(config)
    print(f"  chosen: {phone_info.get('path') or '(none)'}")
    print(f"  discovery_method: {phone_info.get('discovery_method', 'none')}")

    _section("Harvest DBs (find_phone_link_databases)")
    dbs = find_phone_link_databases()
    if dbs:
        for db in dbs:
            print(f"  {db}")
    else:
        print("  (none)")

    _section("Path fallback")
    fb = fallback_status(config)
    for key in (
        "label",
        "enabled",
        "engine",
        "package_roots",
        "packages_wide",
        "timeout_seconds",
        "max_results",
    ):
        print(f"  {key}: {fb.get(key)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
