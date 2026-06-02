from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)

from telelink.harvest import extract_images_from_notification_xml
from telelink.models import MessageEvent
from telelink.notif_seen import NotificationSeenStore

_TOAST_KIND = 1
_DEFAULT_POLL_TIMEOUT = 30.0
_ISSUE_COOLDOWN = 120.0


def _poll_timeout_seconds(config: dict[str, Any]) -> float:
    listener = config.get("listener") or {}
    raw = listener.get("poll_timeout_seconds", _DEFAULT_POLL_TIMEOUT)
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_POLL_TIMEOUT


def extract_notification_text(notification) -> tuple[str, str]:
    title = ""
    body = ""
    try:
        visual = notification.notification.visual
        for binding in visual.bindings:
            try:
                elements = binding.get_text_elements()
            except Exception:
                continue
            parts = [e.text.strip() for e in elements if getattr(e, "text", None)]
            parts = [p for p in parts if p]
            if not parts:
                continue
            if not title:
                title = parts[0]
            if len(parts) > 1:
                body = " ".join(parts[1:])
            elif not body:
                body = parts[0]
    except Exception:
        pass

    if not body:
        try:
            xml = notification.notification.content.get_xml()
            texts = re.findall(r"<text[^>]*>([^<]+)</text>", xml, flags=re.IGNORECASE)
            texts = [t.strip() for t in texts if t.strip()]
            if texts:
                title = title or texts[0]
                body = " ".join(texts[1:]) if len(texts) > 1 else texts[0]
        except Exception:
            pass

    return title, body


def matches_phone_link(user_notification, config: dict[str, Any]) -> bool:
    pl = config.get("phone_link", {})
    names = {n.lower() for n in pl.get("app_names", [])}
    aumids = {a.lower() for a in pl.get("app_user_model_ids", [])}

    app_info = user_notification.app_info
    display = (app_info.display_info.display_name or "").lower()
    aumid = (app_info.app_user_model_id or "").lower()

    if display in names or aumid in aumids:
        return True
    if "yourphone" in aumid or "phone link" in display:
        return True
    return False


class NotificationPoller:
    def __init__(
        self,
        config: dict[str, Any],
        on_message: Callable[[MessageEvent], None],
        on_image: Callable[[MessageEvent], None] | None = None,
        *,
        on_poll_issue: Callable[[str, str], None] | None = None,
        quiet_poll_issues: bool = False,
    ) -> None:
        self.config = config
        self.on_message = on_message
        self.on_image = on_image
        self._on_poll_issue = on_poll_issue
        self._quiet_poll_issues = quiet_poll_issues
        self._poll_timeout = _poll_timeout_seconds(config)
        self._issue_last: dict[str, float] = {}
        self._seen_images: set[str] = set()
        self._listener = UserNotificationListener.current
        out_dir = Path(config.get("output", {}).get("dir", "./data"))
        self._seen_store = NotificationSeenStore(out_dir / "notif-seen.txt")
        self._toast_scratch = Path(tempfile.gettempdir()) / "telelink" / "toast"
        self._toast_scratch.mkdir(parents=True, exist_ok=True)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._changed_token = None

    def _report_poll_issue(self, kind: str, message: str) -> None:
        if self._quiet_poll_issues:
            return
        now = time.monotonic()
        if now - self._issue_last.get(kind, 0.0) < _ISSUE_COOLDOWN:
            return
        self._issue_last[kind] = now
        if self._on_poll_issue is not None:
            self._on_poll_issue(kind, message)
            return
        print(f"[telelink] {message}", flush=True)

    def _bind_change_listener(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._wake = asyncio.Event()

        def _on_changed(_sender, _args) -> None:
            if self._wake is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(self._wake.set)

        try:
            self._changed_token = self._listener.add_notification_changed(_on_changed)
        except Exception:
            self._changed_token = None

    async def ensure_access(self) -> bool:
        status = self._listener.get_access_status()
        if status == UserNotificationListenerAccessStatus.ALLOWED:
            return True
        status = await self._listener.request_access_async()
        return status == UserNotificationListenerAccessStatus.ALLOWED

    async def _fetch_notifications(self):
        return await asyncio.wait_for(
            self._listener.get_notifications_async(_TOAST_KIND),
            timeout=self._poll_timeout,
        )

    async def poll_once(self) -> int:
        """Poll action center; returns number of new messages ingested."""
        notifications = await self._fetch_notifications()
        active_slots: set[str] = set()
        ingested = 0

        for user_note in notifications:
            if not matches_phone_link(user_note, self.config):
                continue

            title, body = extract_notification_text(user_note)
            if not body and not title:
                continue

            app_info = user_note.app_info
            app_id = app_info.app_user_model_id or ""
            app_name = app_info.display_info.display_name or "Phone Link"
            text = body or title
            note_id = int(user_note.id)
            slot = f"{app_id}|{note_id}"
            active_slots.add(slot)

            if not self._seen_store.is_new(app_id, note_id, title, text):
                continue

            xml = ""
            try:
                xml = user_note.notification.content.get_xml()
            except Exception:
                pass

            try:
                from telelink.call_log import try_record_call
                from telelink.session import get_session

                sess = get_session()
                recorded = try_record_call(
                    config=self.config,
                    store=sess.call_log_store,
                    title=title,
                    body=text,
                    notification_app=app_name,
                    xml=xml,
                    contact_store=sess.contact_store,
                )
                if recorded is not None:
                    ingested += 1
                    continue
            except Exception:
                pass

            ingested += 1
            sender = title if title and title != text else ""
            self.on_message(
                MessageEvent(
                    sender_display=sender,
                    body=text,
                    source="phone_link",
                    notification_app=app_name,
                )
            )

            if self.on_image:
                try:
                    if not xml:
                        xml = user_note.notification.content.get_xml()
                    for img_path in extract_images_from_notification_xml(
                        xml, self._toast_scratch
                    ):
                        ikey = hashlib.sha256(img_path.read_bytes()).hexdigest()[:24]
                        if ikey in self._seen_images:
                            continue
                        self._seen_images.add(ikey)
                        self.on_image(
                            MessageEvent(
                                sender_display=sender,
                                body=text,
                                source="toast_image",
                                notification_app=app_name,
                                file_path=img_path,
                            )
                        )
                except Exception:
                    pass

        self._seen_store.prune_slots(active_slots)
        return ingested

    async def run_loop(self, stop_event: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        self._bind_change_listener(loop)
        interval = float(self.config.get("listener", {}).get("poll_seconds", 2))
        idle_polls = 0

        while not stop_event.is_set():
            try:
                n = await self.poll_once()
                if n:
                    idle_polls = 0
                else:
                    idle_polls += 1
            except asyncio.TimeoutError:
                self._report_poll_issue(
                    "timeout",
                    "notification poll timed out — retrying",
                )
            except Exception as exc:
                self._report_poll_issue("error", f"notification poll error: {exc}")

            # Back off slightly when idle so we do not hammer WinRT.
            wait = interval if idle_polls < 3 else min(interval * 2, 8.0)

            wake = self._wake
            if wake is None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                continue

            wake.clear()
            stop_task = asyncio.create_task(stop_event.wait())
            wake_task = asyncio.create_task(wake.wait())
            try:
                done, pending = await asyncio.wait(
                    {stop_task, wake_task},
                    timeout=wait,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
            except Exception:
                for t in (stop_task, wake_task):
                    if not t.done():
                        t.cancel()
