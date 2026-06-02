"""Intake server uptime reminders (interactive shell only)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from telelink import chalk, ink_ui, pretty
from telelink.config import load_config
from telelink.duration import format_duration
from telelink.intake_runtime import intake_pid_file, is_intake_running

MARGIN = ink_ui.MARGIN
_INTERVAL_SECONDS = 600
_STATE_NAME = ".intake-run.json"

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def _state_path(config: dict[str, Any]) -> Path:
    return Path(config["output"]["dir"]) / _STATE_NAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _write_state(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _read_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("started_at", "last_activity"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def mark_intake_started(config: dict[str, Any] | None = None) -> None:
    config = config or load_config()
    path = _state_path(config)
    now = _utc_now().isoformat()
    with _lock:
        state = _read_state(path)
        state["started_at"] = now
        if "last_activity" not in state:
            state.pop("last_activity", None)
        _write_state(path, state)


def touch_intake_activity(config: dict[str, Any] | None = None) -> None:
    config = config or load_config()
    path = _state_path(config)
    now = _utc_now().isoformat()
    with _lock:
        state = _read_state(path)
        if not state.get("started_at"):
            state["started_at"] = now
        state["last_activity"] = now
        _write_state(path, state)


def clear_intake_run_state(config: dict[str, Any] | None = None) -> None:
    config = config or load_config()
    path = _state_path(config)
    with _lock:
        path.unlink(missing_ok=True)


def ensure_intake_run_state(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Ensure state file exists while intake health responds."""
    config = config or load_config()
    path = _state_path(config)
    with _lock:
        state = _read_state(path)
        if state.get("started_at"):
            return state
        started = _utc_now().isoformat()
        pid_path = intake_pid_file(config)
        if pid_path.exists():
            try:
                started = datetime.fromtimestamp(
                    pid_path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat()
            except OSError:
                pass
        state = {"started_at": started}
        _write_state(path, state)
        return state


def _ago_label(dt: datetime | None, *, empty: str) -> str:
    if dt is None:
        return empty
    seconds = max(0, int((_utc_now() - dt).total_seconds()))
    if seconds < 45:
        return "just now"
    return f"{format_duration(seconds)} ago"


def _uptime_label(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    seconds = max(0, int((_utc_now() - dt).total_seconds()))
    if seconds < 60:
        return "under 1m"
    return format_duration(seconds)


def emit_intake_running_reminder(
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> bool:
    """Print a reminder when the intake HTTP server is listening."""
    config = config or load_config()
    if not is_intake_running(config):
        if force:
            pretty.warn("intake server is not running")
        return False

    state = ensure_intake_run_state(config)
    started = _parse_iso(state.get("started_at", ""))
    last = _parse_iso(state.get("last_activity", "")) if state.get("last_activity") else None

    uptime = _uptime_label(started)
    activity = _ago_label(last, empty="no uploads yet")

    missed_suffix = ""
    try:
        from telelink.calls_remind import intake_reminder_missed_suffix

        missed_suffix = intake_reminder_missed_suffix(config)
    except Exception:
        pass

    pretty.info(
        "INTAKE",
        f"still running · up {uptime} · last activity {activity}{missed_suffix}",
    )
    print(
        f"{MARGIN}{chalk.muted('Listening for phone uploads —')} "
        f"{chalk.command('intake stop')} {chalk.muted('to shut down')}",
        flush=True,
    )
    return True


def start_intake_remind_daemon(config_loader: Callable[[], dict[str, Any]]) -> None:
    global _thread, _started

    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()

        def _loop() -> None:
            while not _stop.is_set():
                if _stop.wait(_INTERVAL_SECONDS):
                    break
                try:
                    cfg = config_loader()
                    if is_intake_running(cfg):
                        emit_intake_running_reminder(cfg)
                except Exception:
                    pass

        _thread = threading.Thread(
            target=_loop,
            name="telelink-intake-remind",
            daemon=True,
        )
        _thread.start()


def stop_intake_remind_daemon() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
