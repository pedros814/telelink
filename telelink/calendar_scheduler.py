"""Fire due calendar events (scheduled SMS)."""

from __future__ import annotations

import threading
from typing import Any, Callable

from telelink import chalk, ink_ui, pretty
from telelink.calendar_store import event_receiver_label

MARGIN = ink_ui.MARGIN

_lock = threading.Lock()
_process_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_started = False


def _execute_send(event: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    from telelink.contacts import looks_like_phone
    from telelink.messaging import expand_message_body, resolve_send_recipient, send_message
    from telelink.session import get_session

    session = get_session()
    store = session.contact_store
    store.reload_from_disk()

    raw_to = (event.get("to") or "").strip()
    body = (event.get("body") or "").strip()
    if not body:
        return False, "message body is empty"

    try:
        if looks_like_phone(raw_to):
            from telelink.contacts import normalize_phone

            phone = normalize_phone(raw_to)
            display = raw_to
        else:
            phone, display = resolve_send_recipient(raw_to, store=store)
        text = expand_message_body(body, config)
        record = send_message(
            phone,
            text,
            config=config,
            contact_name=display,
        )
    except Exception as exc:
        return False, str(exc)

    dial = record.get("dial") or record.get("to_phone") or ""
    note = record.get("note") or ""
    if record.get("auto_sent"):
        return True, f"sent to {dial} — {note}".strip(" —")
    if record.get("send_clicked"):
        return True, f"clicked send to {dial} — {note}".strip(" —")
    return True, f"compose opened for {dial} — {note}".strip(" —")


def process_due_events(config: dict[str, Any]) -> int:
    """Claim due pending events, send once, mark completed/failed. Returns count completed."""
    from telelink.session import get_session

    with _process_lock:
        db = get_session().db
        claimed = db.calendar_claim_due()
        if not claimed:
            return 0

        completed = 0
        for event in claimed:
            eid = event["id"]
            if event["kind"] != "send_sms":
                db.calendar_finalize(eid, status="skipped", error="unsupported kind")
                continue
            ok, note = _execute_send(event, config)
            if ok:
                if db.calendar_finalize(eid, status="completed", error=note):
                    receiver = event_receiver_label(event)
                    pretty.info(
                        "CALENDAR",
                        f"scheduled event to {receiver} was completed.",
                    )
                    if note:
                        print(f"{MARGIN}{chalk.muted(note)}", flush=True)
                    completed += 1
            else:
                db.calendar_finalize(eid, status="failed", error=note)
                pretty.warn(f"calendar {event['name']} failed: {note}")
        return completed


def start_calendar_scheduler(config_loader: Callable[[], dict[str, Any]]) -> None:
    global _thread, _started

    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()

        def _loop() -> None:
            while not _stop.is_set():
                try:
                    cfg = config_loader()
                    cal = cfg.get("calendar") or {}
                    if cal.get("enabled", True) is False:
                        if _stop.wait(30):
                            break
                        continue
                    poll = cal.get("poll_seconds", 30)
                    process_due_events(cfg)
                    try:
                        from telelink.calendar_google import maybe_sync_google

                        maybe_sync_google(cfg)
                    except Exception:
                        pass
                except Exception:
                    pass
                if _stop.wait(max(5, int(poll))):
                    break

        _thread = threading.Thread(
            target=_loop,
            name="telelink-calendar-scheduler",
            daemon=True,
        )
        _thread.start()


def stop_calendar_scheduler() -> None:
    global _started
    _stop.set()
    with _lock:
        _started = False
