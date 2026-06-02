"""Run intake server on LAN or via public tunnel; deliver URL via QR or SMS."""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from telelink import chalk, ink_ui, pretty
from telelink.config import load_config
from telelink.intake import IntakeServer, get_lan_ip
from telelink.intake_tunnel import (
    public_tunnel_url,
    start_public_tunnel,
    stop_public_tunnel,
)
from telelink.share_delivery import deliver_share_qr, deliver_share_sms, pick_share_delivery

MARGIN = ink_ui.MARGIN

_standalone: IntakeServer | None = None
_we_own_server = False


def intake_pid_file(config: dict[str, Any] | None = None) -> Path:
    if config is None:
        config = load_config()
    return Path(config["output"]["dir"]) / "intake.pid"


def intake_page_url(config: dict[str, Any] | None = None, *, global_mode: bool = False) -> str:
    config = config or load_config()
    if global_mode:
        pub = public_tunnel_url(config=config)
        if pub:
            return pub
    port = int(config.get("intake", {}).get("port", 8787))
    return f"http://{get_lan_ip()}:{port}/"


def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def is_intake_running(config: dict[str, Any] | None = None) -> bool:
    config = config or load_config()
    port = int(config.get("intake", {}).get("port", 8787))
    return _health_ok(port)


def _make_handler() -> Callable[[str, str, bytes | None, str], None]:
    from telelink.service import TeleLinkService
    from telelink.session import get_session

    session = get_session()
    service = TeleLinkService(session=session)

    def handler(sender: str, message: str, image: bytes | None, filename: str) -> None:
        service.ingest_upload(sender, message, image, filename)

    return handler


def _pids_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            import subprocess

            script = (
                f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
                "Select-Object -ExpandProperty OwningProcess -Unique"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            for line in (r.stdout or "").splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            import subprocess

            r = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for line in (r.stdout or "").splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return pids


def _kill_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import subprocess

        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return r.returncode == 0
    try:
        import os
        import signal

        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def stop_intake_server(*, config: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Stop intake HTTP server and any public tunnel."""
    global _standalone, _we_own_server
    config = config or load_config()
    port = int(config.get("intake", {}).get("port", 8787))

    stop_public_tunnel(config=config)

    if _standalone and _we_own_server:
        _standalone.stop()
        _standalone = None
        _we_own_server = False

    intake_pid_file(config).unlink(missing_ok=True)
    try:
        from telelink.intake_remind import clear_intake_run_state

        clear_intake_run_state(config)
    except Exception:
        pass

    killed: list[int] = []
    if _health_ok(port):
        for pid in _pids_on_port(port):
            if _kill_pid(pid):
                killed.append(pid)

    if killed or not _health_ok(port):
        return True, "intake server stopped"
    if _health_ok(port):
        return False, f"intake still running on port {port} (stop the process using that port)"
    return True, "intake server stopped"


def _intake_server_factory(config: dict[str, Any], *, global_mode: bool):
    intake = config.get("intake", {}) or {}
    backend = str(intake.get("global_server", "pyhttpd")).lower()
    if global_mode and backend != "stdlib":
        from telelink.intake_pyhttpd import PyhttpdIntakeServer

        return PyhttpdIntakeServer
    return IntakeServer


def ensure_intake_server(
    *,
    config: dict[str, Any] | None = None,
    global_mode: bool = False,
) -> tuple[str, bool]:
    """Start intake if needed. Returns (share URL, we_started_it)."""
    global _standalone, _we_own_server
    config = config or load_config()
    port = int(config.get("intake", {}).get("port", 8787))
    lan_url = f"http://{get_lan_ip()}:{port}/"

    started = False
    if not _health_ok(port):
        if _standalone is None:
            try:
                server_cls = _intake_server_factory(config, global_mode=global_mode)
                _standalone = server_cls(config, _make_handler())
                _standalone.start(quiet=global_mode)
                started = True
                _we_own_server = True
                pid_path = intake_pid_file(config)
                pid_path.parent.mkdir(parents=True, exist_ok=True)
                pid_path.write_text(str(port), encoding="utf-8")
                try:
                    from telelink.intake_remind import mark_intake_started

                    mark_intake_started(config)
                except Exception:
                    pass
            except OSError as exc:
                _standalone = None
                pretty.warn(f"could not start intake on port {port}: {exc}")
                return lan_url, False

    share_url = lan_url
    if global_mode:
        try:
            share_url = start_public_tunnel(port, config=config)
            pretty.info("INTAKE", "public URL ready (internet)")
        except RuntimeError as exc:
            pretty.warn(str(exc))
            pretty.info("INTAKE", f"LAN only: {pretty.link(lan_url)}")
            share_url = lan_url

    return share_url, started


def _pick_delivery() -> str:
    return pick_share_delivery(prompt="How do you want to share the intake link?")


def deliver_qr(url: str, *, global_mode: bool = False) -> None:
    label = "scan from any network" if global_mode else "scan with your phone (same Wi-Fi)"
    deliver_share_qr(
        url,
        caption="Scan to open TeleLink intake",
        tag="INTAKE",
        hint=label,
    )


def deliver_sms(url: str, *, config: dict[str, Any] | None = None, global_mode: bool = False) -> None:
    from telelink.share_delivery import share_link_sms_body

    config = config or load_config()
    if global_mode:
        body = share_link_sms_body("TeleLink intake — open from anywhere", url)
    else:
        body = share_link_sms_body("TeleLink intake — same Wi-Fi as your PC", url)
    hint = "scan from any network" if global_mode else "scan with your phone (same Wi-Fi)"
    deliver_share_sms(
        url,
        body=body,
        config=config,
        tag="INTAKE",
        qr_caption="Scan to open TeleLink intake",
        qr_hint=hint,
    )


def run_intake_session(
    *,
    mode: str | None = None,
    block: bool = False,
    global_mode: bool = False,
    config: dict[str, Any] | None = None,
) -> int:
    """Start intake server, deliver URL, optionally wait for uploads."""
    config = config or load_config()
    if not config.get("intake", {}).get("enabled", True):
        pretty.warn("intake is disabled in config.yaml (intake.enabled)")
        return 1

    url, started = ensure_intake_server(config=config, global_mode=global_mode)
    if global_mode:
        backend = str(config.get("intake", {}).get("global_server", "pyhttpd")).lower()
        engine = "pyhttpd" if backend != "stdlib" else "stdlib"
        pretty.info("INTAKE", f"global server ({engine}) — reachable from the internet")
        print(f"{MARGIN}{chalk.muted('Security:')} {chalk.plain('anyone with the link can upload. Set intake.token in config.yaml.')}", flush=True)
    else:
        pretty.info("INTAKE", "LAN server ready — phone on same Wi-Fi")
    print(f"{MARGIN}{chalk.muted('Share')} {pretty.link(url)}", flush=True)
    print(f"{MARGIN}{chalk.plain('Upload files, messages, or links from your phone browser.')}", flush=True)
    print(flush=True)

    choice = (mode or "").lower() or _pick_delivery()
    if choice in ("sms", "text", "message", "2"):
        deliver_sms(url, config=config, global_mode=global_mode)
    else:
        deliver_qr(url, global_mode=global_mode)

    if block:
        print(f"{MARGIN}{chalk.muted('Listening for uploads — Ctrl+C to stop')}", flush=True)
        try:
            import time

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(flush=True)
            stop_intake_server(config=config)
            pretty.info("INTAKE", "stopped")
    elif started or global_mode:
        print(
            f"{MARGIN}{chalk.muted('Server running —')} {chalk.command('intake stop')} {chalk.muted('to shut down')}",
            flush=True,
        )

    return 0


def normalize_share_url(raw: str) -> str:
    text = " ".join(raw.split()).strip()
    if not text:
        raise ValueError("URL or text required")
    if re.match(r"^https?://", text, re.I):
        return text
    if "." in text or text.lower().startswith("www."):
        return "https://" + text.lstrip("/")
    return "https://" + text
