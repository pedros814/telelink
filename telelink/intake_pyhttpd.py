"""Global intake HTTP server via pyhttpd (range-capable, multithreaded)."""

from __future__ import annotations

import os
import tempfile
import threading
from typing import Any, Callable

from telelink.config import expand_path
from telelink.intake import get_lan_ip
from telelink.intake_http import dispatch, set_intake_runtime
from telelink.intake_http import IntakeHttpResponse
from telelink.vendor import pyhttpd


def _send_response(client: pyhttpd.HttpClient, resp: IntakeHttpResponse) -> None:
    headers = dict(resp.extra_headers)
    headers["Content-Type"] = resp.content_type
    msg = pyhttpd.ERROR_DICT.get(resp.code, "OK")
    client.send(resp.code, msg, resp.body, headers)


def client_main(client: pyhttpd.HttpClient, evt_done: threading.Event) -> None:
    """pyhttpd app entry — TeleLink intake routes + ranged file downloads."""
    attachments_root = getattr(client_main, "attachments_root", "")

    while client.keep_alive and client.active:
        req = client.read_request()
        if req is None:
            break

        if pyhttpd.auth_list:
            auth = req["headers"].get("authorization", "")
            if not pyhttpd.check_authed(auth):
                client.send(
                    401,
                    "Unauthorized",
                    b"",
                    {"WWW-Authenticate": 'Basic realm="TeleLink intake"'},
                )
                break

        method = req["method"]
        url = req["url"]
        path = url.split("?", 1)[0]

        if method == "GET" and path.startswith("/files/"):
            rel = path[len("/files/") :].lstrip("/")
            if not rel or ".." in rel.replace("\\", "/"):
                client.send_error(403)
                continue
            fs = os.path.join(attachments_root, rel.replace("/", os.sep))
            if os.path.isfile(fs) and pyhttpd.sec_check(fs, attachments_root):
                client.serve_file(fs, int(req.get("range", 0)))
            else:
                client.send_error(404)
            continue

        body = b""
        if method == "POST":
            try:
                cl = int(req["headers"].get("content-length", "0"))
            except ValueError:
                cl = 0
            if cl and "postdata" not in req:
                body = client.read_body(cl)

        resp = dispatch(method, path, req["headers"], body)
        _send_response(client, resp)

    client.disconnect()
    evt_done.set()


class PyhttpdIntakeServer:
    """Intake server using vendored pyhttpd (used for intake global)."""

    def __init__(
        self,
        config: dict[str, Any],
        handler: Callable[[str, str, bytes | None, str], None],
    ) -> None:
        intake = config.get("intake", {})
        self.config = config
        self.host = intake.get("host", "0.0.0.0")
        self.port = int(intake.get("port", 8787))
        self._handler = handler
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._hs: pyhttpd.HttpSrv | None = None
        from pathlib import Path

        out = config.get("output", {})
        base = Path(expand_path(str(out.get("dir", "./data"))))
        rel = str(out.get("attachments_dir", "attachments"))
        self._attachments = os.path.normpath(str(expand_path(rel) if os.path.isabs(rel) else base / rel))

    @property
    def page_url(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}/"

    @property
    def url(self) -> str:
        return f"{self.page_url.rstrip('/')}/intake"

    def _serve_loop(self) -> None:
        root = tempfile.gettempdir()
        client_main.attachments_root = self._attachments
        os.makedirs(self._attachments, exist_ok=True)

        auth_file = (self.config.get("intake", {}) or {}).get("basic_auth_file", "")
        if auth_file:
            pyhttpd.read_auth_file(str(expand_path(auth_file)))

        hs = pyhttpd.HttpSrv(self.host, self.port, root)
        hs.setup()
        self._hs = hs
        threads: list[tuple[threading.Thread, threading.Event]] = []

        while not self._stop.is_set():
            if self._stop.is_set():
                break
            client = hs.wait_client(timeout=1.0)
            if client is None:
                continue
            if self._stop.is_set():
                client.disconnect()
                break
            done = threading.Event()
            thread = threading.Thread(target=client_main, args=(client, done), daemon=True)
            thread.start()
            threads = [(t, ev) for t, ev in threads if not ev.is_set()]
            for t, ev in threads:
                t.join(timeout=0)
            threads.append((thread, done))

        if self._hs:
            self._hs.shutdown()
            self._hs = None

    def start(self, *, quiet: bool = False) -> None:
        token = self.config.get("intake", {}).get("token", "") or ""
        set_intake_runtime(self._handler, token)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve_loop, name="telelink-pyhttpd-intake", daemon=True)
        self._thread.start()
        if not quiet:
            print(f"[telelink] intake server (pyhttpd)  {self.page_url}")

    def stop(self) -> None:
        self._stop.set()
        hs = self._hs
        if hs:
            hs.shutdown()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._hs = None
        set_intake_runtime(None, "")
