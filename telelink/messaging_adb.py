"""Send SMS on a USB-connected Android phone via adb (bypasses Phone Link UI)."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any


def _adb_bin(config: dict[str, Any]) -> str:
    messaging = config.get("messaging") or {}
    path = messaging.get("adb_path") or shutil.which("adb")
    if not path:
        raise RuntimeError("adb not found — install Android platform-tools and add to PATH")
    return str(path)


def _run(adb: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [adb, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def adb_device_ready(config: dict[str, Any]) -> bool:
    adb = _adb_bin(config)
    r = _run(adb, "devices")
    lines = [ln.strip() for ln in (r.stdout or "").splitlines()[1:] if ln.strip()]
    return any(ln.endswith("\tdevice") for ln in lines)


def send_via_adb(phone: str, body: str, *, config: dict[str, Any]) -> dict[str, Any]:
    """Launch SMS intent on Android; many devices send without extra UI."""
    adb = _adb_bin(config)
    if not adb_device_ready(config):
        raise RuntimeError("no adb device — enable USB debugging and connect Android phone")

    digits = re.sub(r"\D", "", phone)
    uri = f"smsto:{digits}"
    text = body.replace('"', '\\"')

    # Prefer direct SENDTO intent (opens default SMS app with body filled)
    r = _run(
        adb,
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.SENDTO",
        "-d",
        uri,
        "--es",
        "sms_body",
        body,
        "--ez",
        "exit_on_sent",
        "true",
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "adb send failed").strip())

    return {
        "method": "adb",
        "uri": uri,
        "auto_sent": True,
        "note": "Sent via Android intent — confirm on device if prompt appears",
    }
