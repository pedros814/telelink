"""Shared intake HTTP handlers (stdlib server + pyhttpd app)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

from telelink.intake import _parse_multipart
from telelink.web_theme import INTAKE_HTML as _INTAKE_HTML
from telelink.web_theme import SUCCESS_HTML as _SUCCESS_HTML
from telelink.web_theme import error_html as _error_html

_intake_callback: Any = None
_auth_token: str = ""


def set_intake_runtime(
    callback: Any,
    auth_token: str,
) -> None:
    global _intake_callback, _auth_token
    _intake_callback = callback
    _auth_token = auth_token or ""


@dataclass
class IntakeHttpResponse:
    code: int
    body: bytes
    content_type: str
    extra_headers: dict[str, str] = field(default_factory=dict)


def _authorized(headers: dict[str, str]) -> bool:
    if not _auth_token:
        return True
    lower = {k.lower(): v for k, v in headers.items()}
    auth = lower.get("authorization", "")
    if auth == f"Bearer {_auth_token}":
        return True
    return lower.get("x-telelink-token", "") == _auth_token


def dispatch(
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> IntakeHttpResponse:
    path = path.split("?", 1)[0]
    lower_headers = {k.lower(): v for k, v in headers.items()}

    if method == "GET":
        return _handle_get(path)
    if method == "POST" and path == "/intake":
        return _handle_post(lower_headers, body)
    return IntakeHttpResponse(
        404,
        json.dumps({"error": "not found"}).encode("utf-8"),
        "application/json",
    )


def _handle_get(path: str) -> IntakeHttpResponse:
    if path in ("", "/", "/intake", "/upload"):
        return IntakeHttpResponse(200, _INTAKE_HTML.encode("utf-8"), "text/html; charset=utf-8")
    if path == "/help":
        payload = {
            "name": "TeleLink intake",
            "page": "/",
            "post": "/intake",
            "fields": ["sender", "message", "link", "file", "image (json base64)"],
        }
        return IntakeHttpResponse(
            200,
            json.dumps(payload).encode("utf-8"),
            "application/json",
        )
    if path == "/health":
        return IntakeHttpResponse(
            200,
            json.dumps({"ok": True}).encode("utf-8"),
            "application/json",
        )
    return IntakeHttpResponse(
        404,
        json.dumps({"error": "not found"}).encode("utf-8"),
        "application/json",
    )


def _handle_post(headers: dict[str, str], body: bytes) -> IntakeHttpResponse:
    if not _authorized(headers):
        return IntakeHttpResponse(
            401,
            json.dumps({"error": "unauthorized"}).encode("utf-8"),
            "application/json",
        )

    ctype = headers.get("content-type", "")
    sender = ""
    message = ""
    link = ""
    image: bytes | None = None
    filename = "upload.bin"

    if "application/json" in ctype:
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return IntakeHttpResponse(
                400,
                json.dumps({"error": "invalid json"}).encode("utf-8"),
                "application/json",
            )
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
            return IntakeHttpResponse(
                400,
                json.dumps({"error": "no boundary"}).encode("utf-8"),
                "application/json",
            )
        boundary = m.group(1).strip().encode("utf-8")
        parsed = _parse_multipart(body, boundary)
        fields = parsed.get("fields", {})
        sender = fields.get("sender", "")
        message = fields.get("message", "") or fields.get("text", "")
        link = fields.get("link", "") or fields.get("url", "")
        for _field_name, fname, data in parsed.get("files", []):
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

    accept_html = "text/html" in headers.get("accept", "")

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
                return IntakeHttpResponse(
                    500,
                    _error_html(str(exc)).encode("utf-8"),
                    "text/html; charset=utf-8",
                )
            return IntakeHttpResponse(
                500,
                json.dumps({"error": str(exc)}).encode("utf-8"),
                "application/json",
            )

    if accept_html:
        return IntakeHttpResponse(200, _SUCCESS_HTML.encode("utf-8"), "text/html; charset=utf-8")
    return IntakeHttpResponse(
        200,
        json.dumps({"ok": True, "saved": True}).encode("utf-8"),
        "application/json",
    )
