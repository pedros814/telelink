from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from telelink.duration import parse_duration

DEFAULT_CONFIG_NAME = "config.yaml"

DISCOVER_GLOBS = (
    "LocalState/photos",
    "LocalState/Images",
    "LocalCache/images",
    "LocalCache/Photos",
)


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def discover_phone_link_folders() -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    candidates = [
        expand_path("%USERPROFILE%/Pictures/Phone Link"),
        expand_path("%USERPROFILE%/Pictures/Cross Device"),
        expand_path("%USERPROFILE%/Pictures/iPhone"),
        expand_path("%USERPROFILE%/Pictures/iCloud Photos"),
        expand_path("%USERPROFILE%/iCloudDrive"),
        expand_path("%USERPROFILE%/Downloads"),
        expand_path("%USERPROFILE%/Downloads/Phone Link"),
        expand_path("%USERPROFILE%/Pictures/Screenshots"),
    ]

    from telelink.harvest import _pkg_roots

    for pkg_root in _pkg_roots():
        for rel in DISCOVER_GLOBS:
            candidates.append(pkg_root / rel.replace("/", os.sep))
        try:
            for p in pkg_root.glob("LocalCache/Indexed/*/User/*/Recent Photos"):
                if p.is_dir():
                    candidates.append(p)
        except OSError:
            pass
        try:
            for p in pkg_root.rglob("*"):
                if p.is_dir() and p.name.lower() in ("photos", "images", "media"):
                    candidates.append(p)
        except OSError:
            pass

    for p in candidates:
        key = str(p)
        if p.exists() and key not in seen:
            seen.add(key)
            found.append(key)

    if not found:
        try:
            from telelink.phone_link_fallback import fallback_find_media_folders

            for folder in fallback_find_media_folders():
                if folder not in seen:
                    seen.add(folder)
                    found.append(folder)
        except ImportError:
            pass

    return found


def load_config(path: Path | None = None) -> dict[str, Any]:
    root = Path.cwd()
    config_path = path or root / DEFAULT_CONFIG_NAME
    if not config_path.exists():
        example = root / "config.example.yaml"
        if example.exists():
            import shutil

            shutil.copy(example, config_path)
        else:
            raise FileNotFoundError(
                f"No {DEFAULT_CONFIG_NAME} found. Copy config.example.yaml to config.yaml."
            )

    with config_path.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    pl = raw.setdefault("phone_link", {})
    pl.setdefault("contacts_db", "")
    pl.setdefault("calling_db", "")
    fb = pl.setdefault("fallback", {})
    legacy = pl.pop("search", None) or {}
    for key in ("enabled", "timeout_seconds", "max_results"):
        if key in legacy:
            fb.setdefault(key, legacy[key])
    if "allow_packages_wide_search" in legacy:
        fb.setdefault("packages_wide", legacy["allow_packages_wide_search"])
    if str(legacy.get("engine", "")).lower() == "everything":
        fb.setdefault("engine", "powershell")
    elif "engine" in legacy:
        fb.setdefault("engine", legacy["engine"])
    fb.setdefault("enabled", True)
    fb.setdefault("engine", "powershell")
    fb.setdefault("packages_wide", True)
    fb.setdefault("timeout_seconds", 30)
    fb.setdefault("max_results", 20)
    watch = [str(expand_path(p)) for p in pl.get("watch_folders", [])]
    if pl.get("auto_discover_folders", True):
        for p in discover_phone_link_folders():
            if p not in watch:
                watch.append(p)
    pl["watch_folders"] = watch

    out = raw.setdefault("output", {})
    out_dir = expand_path(out.get("dir", "./data"))
    out["dir"] = str(out_dir)
    out["attachments_dir"] = str(out_dir / out.get("attachments_dir", "attachments"))
    caught_name = out.get("caught_file") or out.get("tasks_file") or "caught.jsonl"
    caught_path = out_dir / caught_name
    legacy_tasks = out_dir / "tasks.jsonl"
    if not caught_path.exists() and legacy_tasks.exists():
        caught_path = legacy_tasks
    out["caught_file"] = str(caught_path)
    out["tasks_file"] = out["caught_file"]
    out["contacts_file"] = str(out_dir / out.get("contacts_file", "contacts.jsonl"))
    out["sqlite_file"] = str(out_dir / out.get("sqlite_file", "telelink.db"))
    out["localstorage_file"] = str(out_dir / out.get("localstorage_file", "localstorage.json"))
    out.setdefault("auto_delete_caught", False)
    out["auto_delete_caught_seconds"] = parse_duration(out.get("auto_delete_caught"))

    sync = raw.setdefault("sync", {})
    sync.setdefault("on_startup", True)
    sync.setdefault("import_phone_link_db", True)
    sync.setdefault("import_caught_on_startup", sync.get("import_tasks_on_startup", False))
    sync.setdefault("auto_sync", True)
    sync.setdefault("auto_sync_interval", "15m")
    auto_secs = parse_duration(sync.get("auto_sync_interval", "15m"))
    sync["auto_sync_interval_seconds"] = auto_secs if auto_secs else 900

    cache = raw.setdefault("cache", {})
    cache.setdefault("ttl_seconds", 30)

    messaging = raw.setdefault("messaging", {})
    messaging.setdefault("enabled", True)
    messaging.setdefault("method", "auto")
    messaging.setdefault("log_sent", True)
    messaging.setdefault("sent_log", "sent.jsonl")
    messaging.setdefault("sent_log_max_entries", 5)
    messaging.setdefault("auto_timeout_seconds", 12)
    messaging.setdefault("auto_delay_ms", 2200)
    messaging.setdefault("auto_engine", "pywinauto")
    messaging.setdefault("auto_send_attempts", 2)
    messaging.setdefault("auto_send_retry_gap_ms", 350)
    messaging.setdefault("auto_ctrl_n_before_unfocus", True) # This is needed to prevent input field from locking on and disturbing further sms.
    messaging.setdefault("auto_ctrl_n_gap_ms", 100)
    messaging.setdefault("auto_unfocus_titlebar", True)
    messaging.setdefault("auto_unfocus_delay_ms", 250)
    messaging.setdefault("auto_minimize_after_send", True)
    messaging.setdefault("auto_minimize_delay_ms", 150)
    messaging.setdefault("auto_verify_before_unfocus", True)
    messaging.setdefault("auto_verify_timeout_ms", 8000)
    messaging.setdefault("auto_verify_poll_ms", 400)
    messaging.setdefault("auto_verify_retry_send", True)
    messaging.setdefault("auto_sent_requires_verify", True)
    messaging.setdefault("adb_path", "")

    automation = raw.setdefault("automation", {})
    automation.setdefault("enabled", True)
    automation.setdefault("engine_chain", [messaging.get("auto_engine", "pywinauto")])
    automation.setdefault("max_attempts_per_engine", messaging.get("auto_send_attempts", 2))
    automation.setdefault("verify_timeout_ms", messaging.get("auto_verify_timeout_ms", 8000))
    automation.setdefault("verify_poll_ms", messaging.get("auto_verify_poll_ms", 400))
    pywinauto = automation.setdefault("pywinauto", {})
    pywinauto.setdefault("backend", "uia")
    appium = automation.setdefault("appium", {})
    appium.setdefault("server_url", "http://127.0.0.1:4723")
    appium.setdefault("use_appium_server", False)
    appium.setdefault("phone_link_app", "")
    appium.setdefault("attach_to_existing", True)
    appium.setdefault("session_timeout_seconds", 30)
    fallback = automation.setdefault("fallback", {})
    fallback.setdefault("send_keys_enter", True)
    fallback.setdefault("minimize_showwindow", True)

    raw.setdefault("owner", {})
    raw.setdefault("media", {})
    routing = raw.setdefault("routing", {})
    routing.setdefault("unmatched_label", "unassigned")
    routing.setdefault("only_contacts", routing.get("only_clients", False))
    listener = raw.setdefault("listener", {})
    listener.setdefault("poll_seconds", 2)
    listener.setdefault("poll_timeout_seconds", 30)
    listener.setdefault("auto_start_window", False)
    listener.setdefault("auto_start_delay", "2s")
    auto_delay = parse_duration(listener.get("auto_start_delay", "2s"))
    listener["auto_start_delay_seconds"] = auto_delay if auto_delay is not None else 2.0
    listener.setdefault("console_nudge", True)
    listener.setdefault("console_nudge_interval", "45s")
    if listener.get("console_nudge") is False or str(listener.get("console_nudge", "")).lower() in (
        "false",
        "off",
        "0",
        "no",
    ):
        listener["console_nudge_interval_seconds"] = 0
    else:
        nudge_secs = parse_duration(listener.get("console_nudge_interval", "45s"))
        listener["console_nudge_interval_seconds"] = nudge_secs if nudge_secs else 45

    raw.setdefault("intake", {})
    intake = raw["intake"]
    intake.setdefault("enabled", True)
    intake.setdefault("host", "0.0.0.0")
    intake.setdefault("port", 8787)
    intake.setdefault("token", "")
    intake.setdefault("global_tunnel", "auto")
    intake.setdefault("global_server", "pyhttpd")
    intake.setdefault("public_url", "")
    intake.setdefault("basic_auth_file", "")

    outtake = raw.setdefault("outtake", {})
    outtake.setdefault("prefer", "auto")
    outtake.setdefault("auto_delete", "30m")
    outtake["auto_delete_seconds"] = parse_duration(out.get("auto_delete"))
    outtake.setdefault("auto_delete_poll", "30m")
    poll = parse_duration(outtake.get("auto_delete_poll"))
    outtake["auto_delete_poll_seconds"] = poll if poll else 1800
    gh = outtake.setdefault("github", {})
    gh.setdefault("token", "")
    gh.setdefault("owner", "")
    gh.setdefault("repo", "telelink-sharing")
    gh.setdefault("branch", "main")
    gh.setdefault("path_prefix", "outtake")
    outtake.setdefault("transport", "auto")

    airdrop = raw.setdefault("airdrop", {})
    airdrop.setdefault("enabled", False)
    airdrop.setdefault("mode", "local")
    airdrop.setdefault("binary", "")
    airdrop.setdefault("find_timeout", "20s")
    airdrop.setdefault("discovery_ttl", "60s")
    airdrop.setdefault("cache_dir", "")
    airdrop.setdefault("interface", "awdl0")
    airdrop.setdefault("computer_name", "")
    airdrop.setdefault("computer_model", "TeleLink")
    airdrop.setdefault("default_receiver", "")
    airdrop.setdefault("receivers", [])
    ssh = airdrop.setdefault("ssh", {})
    ssh.setdefault("host", "")
    ssh.setdefault("opendrop_path", "opendrop")
    ssh.setdefault("identity_file", "")

    analyze = raw.setdefault("analyze", {})
    analyze.setdefault("screenshot", True)
    analyze.setdefault("ttl", "4m")
    analyze["ttl_seconds"] = parse_duration(analyze.get("ttl", "4m"))
    analyze.setdefault("width", 700)
    analyze.setdefault("height", 500)
    analyze.setdefault("dir", ".analyze")

    parser = raw.setdefault("parser", {})
    parser.setdefault("urgent_words", [])
    parser.setdefault("muted_words", [])

    calls = raw.setdefault("calls", {})
    calls.setdefault("enabled", True)
    calls.setdefault("file", "calls.jsonl")
    calls.setdefault("ttl", "1d")
    calls["ttl_seconds"] = parse_duration(calls.get("ttl", "1d")) or 86400
    calls.setdefault("remind_interval", "10m")
    calls.setdefault("sync_phone_link_db", True)
    calls.setdefault("sync_limit", 200)
    out["calls_file"] = str(out_dir / calls.get("file", "calls.jsonl"))

    convo = raw.setdefault("convo", {})
    convo.setdefault("enabled", True)
    convo.setdefault("default_limit", 50)
    convo.setdefault("max_all", 500)
    convo.setdefault("ui_fallback", True)
    convo.setdefault("auto_launch_phone_link", True)
    convo.setdefault("auto_open_sms_uri", True)
    convo.setdefault("launch_wait_seconds", 4)
    convo.setdefault("sms_uri_wait_seconds", 2.5)

    calendar = raw.setdefault("calendar", {})
    calendar.setdefault("enabled", True)
    calendar.setdefault("poll_seconds", 30)
    calendar.setdefault("remind_interval", "15m")
    google = calendar.setdefault("google", {})
    google.setdefault("enabled", False)
    google.setdefault("credentials_file", "")
    google.setdefault("token_file", ".calendar-google-token.json")
    google.setdefault("calendar_id", "primary")
    google.setdefault("sync_interval", "5m")

    return raw


def watcher_auto_start_enabled(config: dict[str, Any]) -> bool:
    """True when the interactive shell should spawn the watcher window on startup."""
    val = (config.get("listener") or {}).get("auto_start_window", False)
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def get_config(path: Path | None = None, *, force_reload: bool = False) -> dict[str, Any]:
    """Cached config access with live reload via session when available."""
    try:
        from telelink.session import get_session, reset_session

        if force_reload:
            reset_session()
        return get_session().config_fresh()
    except Exception:
        return load_config(path)
