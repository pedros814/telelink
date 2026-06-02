from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from telelink.classify import (
    classify_channel,
    normalize_sender_id,
    resolve_contact,
    sender_hint_from_path,
    should_ingest,
)
from telelink.context import MessageContext
from telelink.media import store_attachment
from telelink.models import MessageEvent
from telelink.notifications import NotificationPoller
from telelink.notifications_ps import poll_via_powershell
from telelink.ocr import run_ocr
from telelink.parser import build_task, is_muted_message
from telelink.store import CaughtStore
from telelink import chalk, pretty
from telelink.harvest import AutoHarvester
from telelink.iphone_pull import IPhonePuller
from telelink.watcher import start_folder_watchers

try:
    import winrt  # noqa: F401

    HAS_WINRT = True
except ImportError:
    HAS_WINRT = False


class TeleLinkService:
    def __init__(self, config: dict[str, Any] | None = None, *, session=None) -> None:
        from telelink.session import TeleLinkSession, get_session

        sess: TeleLinkSession = session or get_session()
        self._session = sess
        self.config = config if config is not None else sess.config_fresh()
        out = self.config["output"]
        self.store = sess.caught_store
        self.contact_store = sess.contact_store
        if sess.sync_report and sess.sync_report.total:
            pretty.info(
                "SYNC",
                f"{sess.sync_report.total} contacts "
                f"(cfg {sess.sync_report.from_config}, jsonl {sess.sync_report.from_jsonl}, "
                f"plink {sess.sync_report.from_phone_link})",
            )
        window = float(self.config.get("media", {}).get("correlate_window_seconds", 180))
        self._context = MessageContext(window_seconds=window)
        self._stop = asyncio.Event()
        self._stop_thread = threading.Event()
        self._observer = None
        self._harvester: AutoHarvester | None = None
        self._iphone: IPhonePuller | None = None
        self._conout = None
        self._harvest_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="telelink-harvest"
        )
        self._analyze_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="telelink-analyze"
        )

    @property
    def _watcher_mode(self) -> bool:
        return os.environ.get("TELELINK_WATCHER") == "1"

    def _log(self, fn, /, *args, **kwargs) -> None:
        if self._conout:
            self._conout.schedule(fn, *args, **kwargs)
        else:
            fn(*args, **kwargs)

    def _poll_issue(self, kind: str, message: str) -> None:
        """Rate-limited listener issues — watcher stays quiet; shell may warn."""
        if self._watcher_mode:
            return
        self._log(pretty.warn, message, label="LISTEN")

    def _display_caught_row(self, row: dict, *, task: Any | None = None) -> None:
        tag = f"{row.get('channel', '')}/{row.get('message_kind', '')}"
        who = row.get("sender") or row.get("sender_id") or "unknown"
        flag = "MATCH" if row.get("contact_matched") else "other"
        self._log(pretty.task, flag, tag, who, row.get("task", ""))
        self._log(pretty.path, str(self.store.caught_file))
        attachments = row.get("attachments") or []
        if attachments and self._watcher_mode:
            meta_list = row.get("attachment_meta") or []
            meta = meta_list[0] if meta_list and isinstance(meta_list[0], dict) else None
            self._log(
                pretty.attachment_preview,
                attachments[0],
                meta=meta,
                config=self.config,
            )
        if task and task.attachments:
            self._schedule_analyze_snapshot(task, task.attachments[0])

    def _save(self, task) -> None:
        if self.store.save(task):
            self._display_caught_row(task.to_dict(), task=task)

    def _schedule_analyze_snapshot(self, task, att_path: str) -> None:
        from telelink.analyze_snapshot import capture_if_enabled, screenshot_enabled

        if not screenshot_enabled(self.config):
            return

        def _run() -> None:
            capture_if_enabled(
                att_path,
                self._session.config_fresh(),
                task_id=task.id,
                sender=task.sender or task.contact or "",
                channel=task.channel,
                message_kind=task.message_kind,
            )

        try:
            self._analyze_executor.submit(_run)
        except Exception:
            pass

    def _ingest_event(self, event: MessageEvent) -> None:
        sender = event.sender_display
        message = event.body
        channel = classify_channel(sender, message)
        contact, matched = resolve_contact(
            self.config, sender, message, store=self.contact_store
        )

        if not should_ingest(self.config, channel, matched, message=message):
            return

        sender_id = normalize_sender_id(sender)
        if message.strip():
            self._context.push(
                sender_display=sender,
                sender_id=sender_id,
                body=message,
                channel=channel,
                contact=contact,
                contact_matched=matched,
            )

        task = build_task(
            config=self.config,
            message=message,
            sender=sender,
            source=event.source,
            channel=channel,
            contact_matched=matched,
            contact=contact,
            contact_store=self.contact_store,
            notification_app=event.notification_app,
            watch_folder=event.watch_folder,
        )
        self._save(task)

    def _on_message(self, event: MessageEvent) -> None:
        self._ingest_event(event)

    def ingest_upload(
        self,
        sender: str,
        message: str,
        image: bytes | None,
        filename: str,
        *,
        source: str = "network_intake",
    ) -> None:
        """Image/text from iPhone Shortcut or curl on the LAN."""
        channel = classify_channel(sender, message) if sender else "imessage"
        contact, matched = resolve_contact(
            self.config, sender, message, store=self.contact_store
        )
        if not should_ingest(self.config, channel, matched, message=message):
            return

        attachments = []
        ocr_text = ""
        if image:
            tmp = Path(tempfile.gettempdir()) / "telelink" / filename
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(image)
            meta = store_attachment(
                tmp,
                self.config,
                contact=contact,
                channel=channel,
                sender_id=normalize_sender_id(sender),
            )
            dest = Path(meta.path)
            ocr_text = run_ocr(dest, self.config)
            attachments = [meta]
            if not message.strip():
                message = ocr_text or f"Image: {meta.filename}"

        if message.strip():
            self._context.push(
                sender_display=sender,
                sender_id=normalize_sender_id(sender),
                body=message,
                channel=channel,
                contact=contact,
                contact_matched=matched,
            )

        task = build_task(
            config=self.config,
            message=message or "Image upload",
            sender=sender,
            attachments=attachments,
            ocr_text=ocr_text,
            source=source,
            channel=channel,
            contact_matched=matched,
            contact=contact,
            contact_store=self.contact_store,
        )
        self._save(task)

    def _on_image_from_path(self, path: Path) -> None:
        self._on_image(
            MessageEvent(
                sender_display="",
                body="",
                source="auto_harvest",
                file_path=path,
            )
        )

    def _on_image(self, event: MessageEvent) -> None:
        src = event.file_path
        if not src or not src.exists():
            return

        hint = sender_hint_from_path(src) or event.sender_display
        match = self._context.best_match(sender_hint=hint, prefer_matched=True)

        if match:
            sender = match.sender_display
            channel = match.channel
            contact = match.contact
            matched = match.contact_matched
            correlated = match.sender_id
            context_body = match.body
        else:
            sender = hint or "unknown"
            channel = classify_channel(sender, "")
            contact, matched = resolve_contact(self.config, sender, "", store=self.contact_store)
            correlated = ""
            context_body = ""

        if not should_ingest(self.config, channel, matched, message=context_body):
            return

        meta = store_attachment(
            src,
            self.config,
            contact=contact,
            channel=channel,
            sender_id=normalize_sender_id(sender),
        )
        dest = Path(meta.path)
        ocr_text = run_ocr(dest, self.config)

        if ocr_text:
            message = ocr_text
        elif context_body:
            message = f"{context_body} [image: {meta.filename}]"
        else:
            message = f"Image: {meta.filename}"

        if is_muted_message(message, self.config):
            return

        task = build_task(
            config=self.config,
            message=message,
            sender=sender,
            attachments=[meta],
            ocr_text=ocr_text,
            source="folder_watch",
            channel=channel,
            contact_matched=matched,
            contact=contact,
            contact_store=self.contact_store,
            watch_folder=event.watch_folder,
            correlated_from=correlated,
        )
        self._save(task)

    async def _poll_powershell_loop(self) -> None:
        interval = float(self.config.get("listener", {}).get("poll_seconds", 2))

        def _cb(sender: str, text: str, _kind: str) -> None:
            try:
                from telelink.call_log import try_record_call

                recorded = try_record_call(
                    config=self._session.config_fresh(),
                    store=self._session.call_log_store,
                    title=sender or "",
                    body=text,
                    notification_app="Phone Link",
                    contact_store=self._session.contact_store,
                )
                if recorded is not None:
                    return
            except Exception:
                pass
            self._on_message(
                MessageEvent(
                    sender_display=sender,
                    body=text,
                    source="phone_link",
                )
            )

        while not self._stop.is_set():
            try:
                await asyncio.to_thread(
                    poll_via_powershell, self.config, _cb, self._stop_thread
                )
            except PermissionError:
                self._log(
                    pretty.warn,
                    "Notification access denied — Settings > Privacy & security > Notifications",
                    label="LISTEN",
                )
                await asyncio.sleep(30)
            except Exception as exc:
                self._poll_issue("error", f"notification poll error: {exc}")
            await asyncio.sleep(interval)

    async def _harvest_loop(self) -> None:
        if not self._harvester:
            return
        interval = self._harvester.poll_seconds
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                n = await loop.run_in_executor(
                    self._harvest_executor, self._harvester.poll_once
                )
                if n:
                    self._log(pretty.info, "HARVEST", f"{n} image(s)")
            except Exception as exc:
                self._log(pretty.warn, f"harvest error: {exc}")
            await asyncio.sleep(interval)

    async def _iphone_loop(self) -> None:
        if not self._iphone:
            return
        interval = self._iphone.poll_seconds
        while not self._stop.is_set():
            try:
                n = await asyncio.to_thread(self._iphone.poll_once)
                if n:
                    self._log(pretty.info, "IPHONE", f"{n} photo(s)")
            except Exception as exc:
                self._log(pretty.warn, f"iphone pull error: {exc}")
            await asyncio.sleep(interval)

    async def _prune_caught_loop(self) -> None:
        interval = 60.0
        while not self._stop.is_set():
            try:
                config = self._session.config_fresh()
                ttl = config.get("output", {}).get("auto_delete_caught_seconds")
                if ttl:
                    n = await asyncio.to_thread(self.store.prune_older_than, ttl)
                    if n:
                        self._log(pretty.info, "PRUNE", f"removed {n} expired caught")
            except Exception as exc:
                self._log(pretty.warn, f"prune error: {exc}")
            await asyncio.sleep(interval)

    async def _poll_intake_caught_loop(self) -> None:
        """Mirror intake uploads from a separate intake process in the watcher window."""
        path = self.store.caught_file
        offset = path.stat().st_size if path.exists() else 0
        interval = 0.4
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            if not path.exists():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < offset:
                offset = 0
            if size <= offset:
                continue
            try:
                with path.open(encoding="utf-8") as f:
                    f.seek(offset)
                    chunk = f.read()
            except OSError:
                continue
            offset = size
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("source") != "network_intake":
                    continue
                self._display_caught_row(row)

    async def _prune_outtake_loop(self) -> None:
        while not self._stop.is_set():
            interval = 1800.0
            try:
                from telelink.outtake_share import (
                    outtake_auto_delete_poll_seconds,
                    outtake_auto_delete_seconds,
                    prune_outtake_github,
                )

                config = self._session.config_fresh()
                interval = outtake_auto_delete_poll_seconds(config)
                if outtake_auto_delete_seconds(config):
                    n = await asyncio.to_thread(prune_outtake_github, config)
                    if n:
                        self._log(
                            pretty.info,
                            "OUTTAKE",
                            f"deleted {n} expired file(s) from GitHub",
                        )
            except Exception as exc:
                self._log(pretty.warn, f"outtake prune error: {exc}")
            await asyncio.sleep(interval)

    async def _prune_analyze_loop(self) -> None:
        interval = 30.0
        while not self._stop.is_set():
            try:
                from telelink.analyze_snapshot import prune_analyze_dir, screenshot_enabled

                config = self._session.config_fresh()
                if screenshot_enabled(config):
                    n = await asyncio.to_thread(prune_analyze_dir, config)
                    if n:
                        self._log(pretty.info, "ANALYZE", f"removed {n} expired snapshot(s)")
            except Exception as exc:
                self._log(pretty.warn, f"analyze prune error: {exc}")
            await asyncio.sleep(interval)

    async def _prune_calls_loop(self) -> None:
        interval = 300.0
        while not self._stop.is_set():
            try:
                from telelink.call_log import call_log_enabled, call_log_ttl_seconds

                config = self._session.config_fresh()
                if call_log_enabled(config):
                    ttl = call_log_ttl_seconds(config)
                    n = await asyncio.to_thread(
                        self._session.call_log_store.prune_older_than, ttl
                    )
                    if n:
                        self._log(pretty.info, "CALLS", f"removed {n} expired call(s)")
            except Exception as exc:
                self._log(pretty.warn, f"calls prune error: {exc}")
            await asyncio.sleep(interval)

    async def _poll_winrt_loop(self) -> None:
        poller = NotificationPoller(
            self.config,
            self._on_message,
            on_image=self._on_image,
            on_poll_issue=self._poll_issue,
            quiet_poll_issues=self._watcher_mode,
        )
        allowed = await poller.ensure_access()
        if not allowed:
            self._log(
                pretty.warn,
                "Notification access denied — Settings > Privacy & security > Notifications",
                label="LISTEN",
            )
            return
        self._log(pretty.info, "LISTEN", "WinRT notification listener ready")
        await poller.run_loop(self._stop)

    async def run(self) -> None:
        from telelink.conout import get_console_out, prepare_watcher_console
        from telelink.ora import ora

        if self._watcher_mode:
            prepare_watcher_console()
            from telelink.notif_seen import reconcile_seen_if_caught_empty

            if reconcile_seen_if_caught_empty(self.config, self.store):
                self._log(
                    pretty.info,
                    "LISTEN",
                    "cleared stale notification dedup (caught log was empty)",
                )

        loop = asyncio.get_running_loop()
        self._conout = get_console_out()
        self._conout.bind(loop)
        tasks: list[asyncio.Task] = [self._conout.start()]

        if HAS_WINRT:
            self._log(pretty.info, "BACKEND", "WinRT notification listener")
            tasks.append(asyncio.create_task(self._poll_winrt_loop()))
        else:
            self._log(pretty.info, "BACKEND", "PowerShell notification fallback")
            tasks.append(asyncio.create_task(self._poll_powershell_loop()))

        if self._watcher_mode:
            self._observer = start_folder_watchers(
                self.config, self._on_image, log=self._log
            )
        else:
            with ora("Starting folder watchers", kind="scan", prefix="[telelink] "):
                self._observer = start_folder_watchers(self.config, self._on_image)

        if self.config.get("harvest", {}).get("enabled", True):
            self._harvester = AutoHarvester(self.config, self._on_image_from_path)
            if self._watcher_mode:
                dbs = __import__(
                    "telelink.harvest", fromlist=["find_phone_link_databases"]
                ).find_phone_link_databases()
            else:
                with ora("Scanning Phone Link databases", kind="scan", prefix="[telelink] "):
                    dbs = __import__(
                        "telelink.harvest", fromlist=["find_phone_link_databases"]
                    ).find_phone_link_databases()
            self._log(pretty.info, "HARVEST", f"auto-harvest on ({len(dbs)} Phone Link DBs)")

        if self.config.get("iphone_pull", {}).get("enabled", False):
            self._iphone = IPhonePuller(self.config, self._on_image_from_path)
            self._log(pretty.info, "IPHONE", "DCIM pull enabled (pymobiledevice3)")

        if self._harvester:
            tasks.append(asyncio.create_task(self._harvest_loop()))
        if self._iphone:
            tasks.append(asyncio.create_task(self._iphone_loop()))
        if self.config.get("output", {}).get("auto_delete_caught_seconds"):
            tasks.append(asyncio.create_task(self._prune_caught_loop()))
        from telelink.outtake_share import outtake_auto_delete_seconds

        if outtake_auto_delete_seconds(self.config):
            tasks.append(asyncio.create_task(self._prune_outtake_loop()))
        from telelink.analyze_snapshot import screenshot_enabled

        if screenshot_enabled(self.config):
            tasks.append(asyncio.create_task(self._prune_analyze_loop()))
        from telelink.call_log import call_log_enabled

        if call_log_enabled(self.config):
            tasks.append(asyncio.create_task(self._prune_calls_loop()))
        from telelink.sent_log import prune_sent_log, sent_log_max_entries

        if sent_log_max_entries(self.config):
            n = await asyncio.to_thread(prune_sent_log, self.config)
            if n:
                self._log(pretty.info, "SENT", f"trimmed {n} old sent log entr{'y' if n == 1 else 'ies'}")
        if self._watcher_mode:
            tasks.append(asyncio.create_task(self._poll_intake_caught_loop()))
            from telelink.watcher_console_nudge import (
                watcher_console_nudge_interval_seconds,
                watcher_console_nudge_loop,
            )

            nudge_secs = watcher_console_nudge_interval_seconds(self.config)
            if nudge_secs > 0:
                tasks.append(
                    asyncio.create_task(watcher_console_nudge_loop(self._stop, nudge_secs))
                )

        self._log(pretty.info, "LISTEN", "ctrl+c to stop")
        self._log(print, "  auto images: assets/ios-auto-intake.txt")

        try:
            await self._stop.wait()
        finally:
            self._stop_thread.set()
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            if self._observer:
                self._observer.stop()
                self._observer.join()
            try:
                self._harvest_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._harvest_executor.shutdown(wait=False)
            try:
                self._analyze_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._analyze_executor.shutdown(wait=False)

    def request_stop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Signal listener loops to exit — does not cancel the main run() task."""
        self._stop.set()
        self._stop_thread.set()

    def _cancel_all_tasks(self, loop: asyncio.AbstractEventLoop) -> None:
        """Force-cancel every task (second Ctrl+C / hard shutdown)."""

        def _cancel() -> None:
            current = asyncio.current_task(loop)
            for task in asyncio.all_tasks(loop):
                if task is not current and not task.done():
                    task.cancel()

        try:
            loop.call_soon_threadsafe(_cancel)
        except RuntimeError:
            _cancel()

    def run_sync(self) -> None:
        import signal
        import sys

        from telelink.conout import prepare_watcher_console
        from telelink.keys import listen_for_ctrl_c
        from telelink.listener_spawn import clear_watcher_pid, write_watcher_pid

        if self._watcher_mode:
            prepare_watcher_console()

        write_watcher_pid()
        pretty.info("WATCHER", "live — Ctrl+C to stop")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._stop.clear()
        self._stop_thread.clear()

        def trigger_stop() -> None:
            self.request_stop(loop)

        def on_sigint(*_) -> None:
            if self._stop.is_set():
                loop.call_soon_threadsafe(lambda: self._cancel_all_tasks(loop))
                raise KeyboardInterrupt
            loop.call_soon_threadsafe(trigger_stop)

        try:
            signal.signal(signal.SIGINT, on_sigint)
        except Exception:
            pass

        def on_ctrl_c() -> None:
            if self._stop.is_set():
                loop.call_soon_threadsafe(lambda: self._cancel_all_tasks(loop))
            else:
                trigger_stop()

        listen_for_ctrl_c(self._stop_thread, on_stop=on_ctrl_c)

        try:
            loop.run_until_complete(self.run())
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._stop.set()
            self._stop_thread.set()
        finally:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            clear_watcher_pid()
            print("\n" + chalk.plain("stopped"))
