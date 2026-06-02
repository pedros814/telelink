"""Public tunnel for intake (cloudflared / ngrok) — internet-reachable URL."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_URL_RE = re.compile(r"https://[a-zA-Z0-9][-a-zA-Z0-9._]*[a-zA-Z0-9](?:/[^\s]*)?")

_tunnel_proc: subprocess.Popen | None = None
_tunnel_url: str = ""


def _tunnel_pid_file(config: dict[str, Any] | None = None) -> Path:
    if config is None:
        from telelink.config import load_config

        config = load_config()
    base = Path(config["output"]["dir"])
    return base / "intake.tunnel.pid"


def _tunnel_url_file(config: dict[str, Any] | None = None) -> Path:
    if config is None:
        from telelink.config import load_config

        config = load_config()
    base = Path(config["output"]["dir"])
    return base / "intake.tunnel.url"


def _extract_url(text: str) -> str | None:
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(").,;\"'")
        if "trycloudflare.com" in url or "ngrok" in url or "loca.lt" in url:
            return url
    return None


def _read_stream_for_url(proc: subprocess.Popen, *, timeout: float = 45.0) -> str | None:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None and not buf:
            break
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        buf += line
        found = _extract_url(buf)
        if found:
            return found
    return _extract_url(buf)


def _start_cloudflared(local_url: str) -> tuple[subprocess.Popen | None, str | None]:
    exe = shutil.which("cloudflared")
    if not exe:
        return None, None
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", local_url],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    public = _read_stream_for_url(proc, timeout=50.0)
    if public:
        return proc, public
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    return None, None


def _start_ngrok(port: int) -> tuple[subprocess.Popen | None, str | None]:
    exe = shutil.which("ngrok")
    if not exe:
        return None, None
    proc = subprocess.Popen(
        [exe, "http", str(port), "--log=stdout", "--log-format=logfmt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    public = _read_stream_for_url(proc, timeout=40.0)
    if public:
        return proc, public
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    return None, None


def start_public_tunnel(
    port: int,
    *,
    config: dict[str, Any] | None = None,
    method: str = "auto",
) -> str:
    """Start tunnel to localhost:port. Returns public https URL."""
    global _tunnel_proc, _tunnel_url
    stop_public_tunnel(config=config)

    cfg = config or {}
    intake = cfg.get("intake", {})
    manual = str(intake.get("public_url", "") or "").strip()
    if manual:
        _tunnel_url = manual.rstrip("/") + "/"
        return _tunnel_url

    local = f"http://127.0.0.1:{port}"
    method = (method or intake.get("global_tunnel", "auto")).lower()
    proc: subprocess.Popen | None = None
    public: str | None = None

    if method in ("auto", "cloudflared"):
        proc, public = _start_cloudflared(local)
    if not public and method in ("auto", "ngrok"):
        proc, public = _start_ngrok(port)

    if not public or not proc:
        raise RuntimeError(
            "No public tunnel available. Install cloudflared or ngrok, or set "
            "intake.public_url in config.yaml to your own tunnel URL."
        )

    _tunnel_proc = proc
    _tunnel_url = public.rstrip("/") + "/"
    pid_path = _tunnel_pid_file(cfg)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    _tunnel_url_file(cfg).write_text(_tunnel_url, encoding="utf-8")
    return _tunnel_url


def stop_public_tunnel(*, config: dict[str, Any] | None = None) -> None:
    global _tunnel_proc, _tunnel_url
    if config is None:
        from telelink.config import load_config

        config = load_config()

    if _tunnel_proc and _tunnel_proc.poll() is None:
        _tunnel_proc.terminate()
        try:
            _tunnel_proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            _kill_pid_tree(_tunnel_proc.pid)
    _tunnel_proc = None
    _tunnel_url = ""

    pid_path = _tunnel_pid_file(config)
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            _kill_pid_tree(pid)
        except (ValueError, OSError):
            pass
        pid_path.unlink(missing_ok=True)
    _tunnel_url_file(config).unlink(missing_ok=True)


def _kill_pid_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        import os
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def public_tunnel_url(*, config: dict[str, Any] | None = None) -> str:
    if _tunnel_url:
        return _tunnel_url
    if config is None:
        from telelink.config import load_config

        config = load_config()
    path = _tunnel_url_file(config)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""
