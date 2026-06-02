from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "poll-notifications.ps1"


def poll_via_powershell(
    config: dict[str, Any],
    on_message: Callable[[str, str, str], None],
    stop: Event | None = None,
) -> None:
    pl = config.get("phone_link", {})
    app_names = pl.get("app_names", ["Phone Link", "Your Phone"])
    out_dir = Path(config.get("output", {}).get("dir", "./data"))
    seen_file = out_dir / "notif-seen.txt"

    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-SeenFile",
        str(seen_file),
    ]
    for name in app_names:
        args += ["-AppNames", name]

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        deadline = time.monotonic() + 8
        while proc.poll() is None:
            if stop and stop.is_set():
                proc.terminate()
                return
            if time.monotonic() >= deadline:
                proc.kill()
                break
            time.sleep(0.05)
        stdout, stderr = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    except Exception:
        proc.kill()
        raise

    if proc.returncode == 2:
        raise PermissionError(stderr or "Notification access denied")
    if proc.returncode not in (0, None) and stderr:
        raise RuntimeError(stderr.strip())

    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        on_message(row.get("sender", ""), row.get("body", ""), "notification")
