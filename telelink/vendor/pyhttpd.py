#!/usr/bin/env python3
# Vendored from https://github.com/rofl0r/pyhttpd (LGPL-2.1). Python 3 port for TeleLink.

from __future__ import annotations

import base64
import errno
import os
import socket
import threading
from urllib.parse import quote, unquote_plus

ERROR_DICT = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    416: "Range Not Satisfiable",
    500: "Internal Server Error",
    501: "Not Implemented",
    503: "Service Unavailable",
    505: "HTTP Version Not Supported",
}

CONTENT_TYPE_DICT = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".json": "application/json",
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".txt": "text/plain",
}


def _get_content_type(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return CONTENT_TYPE_DICT.get(ext.lower(), "application/octet-stream")


class BufferedSocket:
    """Socket wrapper with read buffering (pyhttpd-style)."""

    def __init__(self, sock: socket.socket | None = None, *, family=socket.AF_INET, type=socket.SOCK_STREAM):
        self.buffer = b""
        self._sock = sock or socket.socket(family, type)

    def setsockopt(self, *args, **kwargs) -> None:
        self._sock.setsockopt(*args, **kwargs)

    def bind(self, addr) -> None:
        self._sock.bind(addr)

    def listen(self, backlog: int) -> None:
        self._sock.listen(backlog)

    def settimeout(self, value: float | None) -> None:
        self._sock.settimeout(value)

    def close(self) -> None:
        self._sock.close()

    def accept(self) -> tuple[BufferedSocket, tuple]:
        conn, addr = self._sock.accept()
        return BufferedSocket(conn), addr

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        return self._sock.recv(bufsize, flags)

    def read(self, bufsize: int, flags: int = 0) -> bytes:
        if self.buffer:
            chunk = self.buffer[:bufsize]
            self.buffer = self.buffer[bufsize:]
            return chunk
        return self.recv(bufsize, flags)

    def readuntil(self, marker: bytes | str, exclude_marker: bool = False, maxbytes: int = -1) -> bytes:
        if isinstance(marker, str):
            marker = marker.encode("latin-1")
        while True:
            p = self.buffer.find(marker)
            if p != -1:
                end = p + (0 if exclude_marker else len(marker))
                out = self.buffer[:end]
                self.buffer = self.buffer[end:]
                return out
            if maxbytes != -1 and len(self.buffer) >= maxbytes:
                self.buffer = b""
                return b""
            chunk = self.recv(4096)
            if not chunk:
                self.buffer = b""
                return b""
            self.buffer += chunk

    def readline(self, exclude_marker: bool = False, maxbytes: int = -1) -> bytes:
        return self.readuntil(b"\n", exclude_marker, maxbytes)


def _parse_req(line: bytes) -> tuple[str, str, str]:
    text = line.decode("latin-1", errors="replace").strip()
    parts = text.split()
    if len(parts) < 2:
        return "", "", ""
    method = parts[0]
    url = parts[1]
    ver = parts[2] if len(parts) > 2 else ""
    return method, url, ver


def _parse_to_dict(s: str, sep: str = ":") -> dict[str, str]:
    result: dict[str, str] = {}
    for line in s.split("\n"):
        p = line.find(sep)
        if p > 0:
            result[line[:p].lower()] = line[p + 1 :].strip()
    return result


def _resolve(host: str, port: int) -> tuple[int, tuple[str, int]]:
    if host in ("0.0.0.0", ""):
        return socket.AF_INET, ("0.0.0.0", port)
    for res in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
        af, _socktype, _proto, _canon, sa = res
        if af in (socket.AF_INET, socket.AF_INET6):
            return af, sa  # type: ignore[return-value]
    return socket.AF_INET, (host, port)


class HttpClient:
    def __init__(self, addr, conn: BufferedSocket, root: str):
        self.addr = addr
        self.conn = conn
        self.root = root
        self.active = True
        self.keep_alive = True

    def _send_i(self, data: bytes) -> bool:
        try:
            self.conn.sendall(data)
            return True
        except OSError:
            return False

    def send_header(self, code: int, msg: str, response_len: int, headers: dict[str, str] | None = None) -> bool:
        h = ""
        if headers:
            h = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        body = f"HTTP/1.1 {code} {msg}\r\n{h}Content-Length: {response_len}\r\n\r\n"
        return self._send_i(body.encode("latin-1"))

    def send(self, code: int, msg: str, response: bytes | str, headers: dict[str, str] | None = None) -> bool:
        if isinstance(response, str):
            response = response.encode("utf-8")
        if not self.send_header(code, msg, len(response), headers):
            return False
        return self._send_i(response)

    def send_error(self, code: int, text: bytes | str | None = None) -> None:
        msg = ERROR_DICT.get(code, "Error")
        if text is None:
            text = f"error {code}: {msg}\r\n"
        if isinstance(text, str):
            text = text.encode("utf-8")
        self.send(code, msg, text)

    def serve_file(self, filename: str, start: int = 0) -> None:
        st = os.stat(filename)
        sz = st.st_size
        headers: dict[str, str] = {}
        ct = _get_content_type(filename)
        if ct:
            headers["Content-Type"] = ct
        if start == 0:
            self.send_header(200, "OK", sz - start, headers)
        elif start >= sz:
            self.send_error(416)
            return
        else:
            headers["Content-Range"] = f"bytes {start}-{sz - 1}/{sz}"
            self.send_header(206, "Partial Content", sz - start, headers)

        sent = 0
        with open(filename, "rb") as handle:
            handle.seek(start)
            while sent < sz - start:
                chunk = handle.read(16384)
                if not chunk:
                    break
                try:
                    self.conn.sendall(chunk)
                except OSError:
                    self.disconnect()
                    break
                sent += len(chunk)

    def read_request(self) -> dict | None:
        try:
            line = self.conn.readline(maxbytes=4096)
        except OSError:
            return None
        if not line:
            return None
        meth, url, ver = _parse_req(line)
        if not ver.startswith("HTTP/"):
            self.send_error(400)
            return None
        if ver not in ("HTTP/1.1", "HTTP/1.0"):
            self.send_error(505)
            return None

        try:
            header_block = self.conn.readuntil(b"\r\n\r\n", maxbytes=16384)
        except OSError:
            self.send_error(400)
            return None
        if not header_block:
            self.send_error(400)
            return None

        headers = _parse_to_dict(header_block.decode("latin-1", errors="replace"))
        result: dict = {
            "method": meth,
            "url": unquote_plus(url),
            "headers": headers,
            "range": 0,
            "getdata": {},
        }
        rng = headers.get("range", "")
        if rng.lower().startswith("bytes="):
            part = rng.split("=", 1)[1].strip()
            if part and part[0] != "-" and part.endswith("-"):
                try:
                    result["range"] = int(part[:-1])
                except ValueError:
                    pass
        try:
            cl = int(headers.get("content-length", "0"))
        except ValueError:
            cl = 0
        ct = headers.get("content-type", "")
        if meth == "GET" and "?" in result["url"]:
            p = result["url"].find("?")
            result["getdata"] = _parse_to_dict(result["url"][p + 1 :].replace("&", "\n"), "=")
            result["url"] = result["url"][:p]
        if meth == "POST" and ct in ("application/x-www-form-urlencoded", "text/plain"):
            body = b""
            while len(body) < cl:
                chunk = self.conn.read(cl - len(body))
                if not chunk:
                    break
                body += chunk
            postdata = _parse_to_dict(body.decode("utf-8", errors="replace"), "=")
            if ct == "application/x-www-form-urlencoded":
                postdata = {k: unquote_plus(v) for k, v in postdata.items()}
            result["postdata"] = postdata
        return result

    def read_body(self, length: int) -> bytes:
        if length <= 0:
            return b""
        body = b""
        while len(body) < length:
            chunk = self.conn.read(length - len(body))
            if not chunk:
                break
            body += chunk
        return body

    def disconnect(self) -> None:
        if self.active:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None  # type: ignore[assignment]
        self.active = False
        self.keep_alive = False


class HttpSrv:
    def __init__(self, listenip: str, port: int, root: str):
        self.port = port
        self.listenip = listenip
        self.root = root.rstrip(os.sep)
        self.s: BufferedSocket | None = None

    def setup(self) -> None:
        af, sa = _resolve(self.listenip, self.port)
        s = BufferedSocket(family=af, type=socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(sa)
        s.listen(128)
        self.s = s

    def wait_client(self, timeout: float | None = None) -> HttpClient | None:
        if self.s is None:
            return None
        if timeout is not None:
            self.s.settimeout(timeout)
        try:
            conn, addr = self.s.accept()
        except socket.timeout:
            return None
        except OSError as exc:
            if exc.errno in (errno.EINTR, errno.EAGAIN, errno.EBADF) or getattr(exc, "winerror", None) == 10038:
                return None
            raise
        finally:
            if timeout is not None and self.s is not None:
                try:
                    self.s.settimeout(None)
                except OSError:
                    pass
        return HttpClient(addr, conn, self.root)

    def shutdown(self) -> None:
        if self.s:
            try:
                self.s.close()
            except OSError:
                pass
            self.s = None


def sec_check(fs: str, root: str) -> bool:
    rp = os.path.normpath(fs)
    return rp == root or rp.startswith(root + os.sep)


auth_list: list[str] = []


def check_authed(auth_str: str) -> bool:
    if not auth_list:
        return True
    if not auth_str.lower().startswith("basic "):
        return False
    return auth_str[6:].strip() in auth_list


def read_auth_file(path: str) -> None:
    global auth_list
    if path == "-":
        line = input("enter username:password: ")
    else:
        line = open(path, encoding="utf-8").readline().strip()
    if ":" not in line:
        raise ValueError("auth string must look like user:pass")
    auth_list = [base64.b64encode(line.encode("utf-8")).decode("ascii")]
