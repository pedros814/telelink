from __future__ import annotations



import base64

import json

import re

import socket

import tempfile

import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from typing import Any, Callable

from urllib.parse import parse_qs

from telelink.web_theme import INTAKE_HTML as _INTAKE_HTML
from telelink.web_theme import SUCCESS_HTML as _SUCCESS_HTML
from telelink.web_theme import error_html as _error_html


def get_lan_ip() -> str:

    try:

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        s.connect(("8.8.8.8", 80))

        ip = s.getsockname()[0]

        s.close()

        return ip

    except OSError:

        return "127.0.0.1"





def _parse_multipart(body: bytes, boundary: bytes) -> dict[str, Any]:

    """Minimal multipart parser for Shortcut / browser uploads."""

    parts: dict[str, Any] = {"fields": {}, "files": []}

    for chunk in body.split(b"--" + boundary):

        if b"Content-Disposition" not in chunk:

            continue

        header_end = chunk.find(b"\r\n\r\n")

        if header_end < 0:

            continue

        header = chunk[:header_end].decode("utf-8", errors="replace")

        data = chunk[header_end + 4 :].rstrip(b"\r\n")

        name_m = re.search(r'name="([^"]+)"', header)

        if not name_m:

            continue

        name = name_m.group(1)

        filename_m = re.search(r'filename="([^"]*)"', header)

        if filename_m and filename_m.group(1):

            parts["files"].append((name, filename_m.group(1), data))

        else:

            parts["fields"][name] = data.decode("utf-8", errors="replace")

    return parts





_intake_callback: Callable[[str, str, bytes | None, str], None] | None = None

_auth_token: str = ""





class IntakeHandler(BaseHTTPRequestHandler):



    def log_message(self, fmt: str, *args) -> None:

        pass



    def _authorized(self) -> bool:

        if not _auth_token:

            return True

        auth = self.headers.get("Authorization", "")

        if auth == f"Bearer {_auth_token}":

            return True

        return self.headers.get("X-Telelink-Token", "") == _auth_token



    def _json(self, code: int, payload: dict) -> None:

        body = json.dumps(payload).encode("utf-8")

        self.send_response(code)

        self.send_header("Content-Type", "application/json")

        self.send_header("Content-Length", str(len(body)))

        self.end_headers()

        self.wfile.write(body)



    def _html(self, code: int, html: str) -> None:

        body = html.encode("utf-8")

        self.send_response(code)

        self.send_header("Content-Type", "text/html; charset=utf-8")

        self.send_header("Content-Length", str(len(body)))

        self.end_headers()

        self.wfile.write(body)



    def do_GET(self) -> None:

        path = self.path.split("?", 1)[0]

        if path in ("", "/", "/intake", "/upload"):

            self._html(200, _INTAKE_HTML)

            return

        if path == "/help":

            self._json(

                200,

                {

                    "name": "TeleLink intake",

                    "page": "/",

                    "post": "/intake",

                    "fields": ["sender", "message", "link", "file", "image (json base64)"],

                },

            )

            return

        if path == "/health":

            self._json(200, {"ok": True})

            return

        self._json(404, {"error": "not found"})



    def do_POST(self) -> None:

        if self.path.split("?", 1)[0] != "/intake":

            self._json(404, {"error": "not found"})

            return

        if not self._authorized():

            self._json(401, {"error": "unauthorized"})

            return



        length = int(self.headers.get("Content-Length", 0))

        body = self.rfile.read(length) if length else b""

        ctype = self.headers.get("Content-Type", "")



        sender = ""

        message = ""

        link = ""

        image: bytes | None = None

        filename = "upload.bin"



        if "application/json" in ctype:

            try:

                data = json.loads(body.decode("utf-8"))

            except json.JSONDecodeError:

                self._json(400, {"error": "invalid json"})

                return

            sender = str(data.get("sender", ""))

            message = str(data.get("message", "") or data.get("text", ""))

            link = str(data.get("link", "") or data.get("url", ""))

            b64 = data.get("image_base64") or data.get("image")

            if b64:

                image = base64.b64decode(b64)

                filename = str(data.get("filename", "upload.jpg"))

        elif "multipart/form-data" in ctype:

            m = re.search(r"boundary=(.+)", ctype)

            if not m:

                self._json(400, {"error": "no boundary"})

                return

            boundary = m.group(1).strip().encode("utf-8")

            parsed = _parse_multipart(body, boundary)

            fields = parsed.get("fields", {})

            sender = fields.get("sender", "")

            message = fields.get("message", "") or fields.get("text", "")

            link = fields.get("link", "") or fields.get("url", "")

            files = parsed.get("files", [])

            for field_name, fname, data in files:

                if data:

                    image = data

                    filename = fname or "upload.bin"

                    break

        else:

            qs = parse_qs(body.decode("utf-8", errors="replace"))

            sender = (qs.get("sender") or [""])[0]

            message = (qs.get("message") or qs.get("text") or [""])[0]

            link = (qs.get("link") or qs.get("url") or [""])[0]



        if link.strip() and not message.strip():

            message = link.strip()

        if link.strip() and link.strip() not in message:

            message = f"{message}\n{link.strip()}".strip() if message.strip() else link.strip()



        accept_html = "text/html" in self.headers.get("Accept", "")



        if _intake_callback:

            try:

                _intake_callback(sender, message, image, filename)

                try:

                    from telelink.intake_remind import touch_intake_activity

                    touch_intake_activity()

                except Exception:

                    pass

            except Exception as exc:

                if accept_html:

                    self._html(500, _error_html(str(exc)))

                else:

                    self._json(500, {"error": str(exc)})

                return



        if accept_html:

            self._html(200, _SUCCESS_HTML)

        else:

            self._json(200, {"ok": True, "saved": True})





class IntakeServer:

    def __init__(

        self,

        config: dict[str, Any],

        handler: Callable[[str, str, bytes | None, str], None],

    ) -> None:

        self.config = config

        intake = config.get("intake", {})

        self.host = intake.get("host", "0.0.0.0")

        self.port = int(intake.get("port", 8787))

        self._handler = handler

        self._httpd: ThreadingHTTPServer | None = None

        self._thread: threading.Thread | None = None



    @property

    def page_url(self) -> str:

        return f"http://{get_lan_ip()}:{self.port}/"



    @property

    def url(self) -> str:

        return f"{self.page_url.rstrip('/')}/intake"



    def start(self, *, quiet: bool = False) -> None:

        global _intake_callback, _auth_token

        _intake_callback = self._handler

        _auth_token = self.config.get("intake", {}).get("token", "") or ""

        self._httpd = ThreadingHTTPServer((self.host, self.port), IntakeHandler)

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

        self._thread.start()

        if not quiet:

            print(f"[telelink] intake server  {self.page_url}")



    def stop(self) -> None:

        global _intake_callback

        if self._httpd:

            self._httpd.shutdown()

            self._httpd = None

        _intake_callback = None


