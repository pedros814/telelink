"""Start and stop Auto-Reply sessions in separate console windows."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


_SESSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _validate_session(session: str) -> str:
    slug = (session or "").strip().lower()
    if not slug or not _SESSION_RE.fullmatch(slug):
        raise ValueError("session must be a slug: [a-z0-9._-], max 64 chars")
    return slug


def _ars_dir(config: dict | None = None) -> Path:
    if config:
        base = Path(config["output"]["dir"])
    else:
        from telelink.config import load_config

        base = Path(load_config()["output"]["dir"])
    return base / "ars"


def ars_pid_file(session: str, config: dict | None = None) -> Path:
    slug = _validate_session(session)
    return _ars_dir(config) / f"{slug}.pid"


def is_ars_running(session: str, config: dict | None = None) -> bool:
    pid_path = ars_pid_file(session, config)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            pid_path.unlink(missing_ok=True)
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        pid_path.unlink(missing_ok=True)
        return False


def write_ars_pid(session: str) -> None:
    pid_path = ars_pid_file(session)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def clear_ars_pid(session: str) -> None:
    ars_pid_file(session).unlink(missing_ok=True)


def _kill_pid(pid: int, *, force: bool = True) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        r = subprocess.run(args, capture_output=True, check=False)
        return r.returncode == 0
    try:
        import signal

        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except OSError:
        return False


def _find_ars_pids(session: str | None = None) -> set[int]:
    pids: set[int] = set()
    if sys.platform == "win32":
        matcher = "telelink ars run"
        if session:
            safe = session.replace("'", "''")
            matcher = f"telelink ars run {safe}"
        try:
            script = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -and $_.CommandLine -match "
                f"'{matcher}' }} | "
                "ForEach-Object { $_.ProcessId }"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            query = "telelink ars run"
            if session:
                query = f"telelink ars run {session}"
            r = subprocess.run(
                ["pgrep", "-f", query],
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


def stop_ars(session: str | None = None, *, force: bool = True) -> tuple[bool, str]:
    """Stop one ARS session, or all ARS sessions when session is None."""
    from telelink.config import load_config

    config = load_config()
    ars_dir = _ars_dir(config)
    targets: set[int] = set()
    pid_files: list[Path] = []

    if session:
        slug = _validate_session(session)
        path = ars_pid_file(slug, config)
        if path.exists():
            pid_files.append(path)
            try:
                targets.add(int(path.read_text(encoding="utf-8").strip()))
            except (ValueError, OSError):
                pass
        targets |= _find_ars_pids(slug)
    else:
        if ars_dir.exists():
            pid_files = sorted(ars_dir.glob("*.pid"))
        for path in pid_files:
            try:
                targets.add(int(path.read_text(encoding="utf-8").strip()))
            except (ValueError, OSError):
                pass
        targets |= _find_ars_pids(None)

    killed: list[int] = []
    for pid in sorted(targets):
        if _kill_pid(pid, force=force):
            killed.append(pid)

    for path in pid_files:
        path.unlink(missing_ok=True)
    if session:
        try:
            clear_ars_pid(session)
        except ValueError:
            pass

    if killed:
        return True, f"stopped ars (pid {', '.join(map(str, killed))})"
    if targets:
        return True, "ars stopped"
    return False, "no ars session running"


def spawn_ars_window(
    session: str,
    contact: str,
    *,
    root: Path | None = None,
) -> bool:
    """Launch `telelink ars run` in a new console. False when already running."""
    slug = _validate_session(session)
    root = root or Path(__file__).resolve().parent.parent
    py = root / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    from telelink.config import load_config

    config = load_config(root / "config.yaml")
    if is_ars_running(slug, config):
        return False

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["TELELINK_ARS"] = "1"
    env["TELELINK_ARS_SESSION"] = slug
    env["TELELINK_ARS_CONTACT"] = contact
    env["TELELINK_ARS_TITLE"] = f"TeleLink ARS — {slug} ({contact})"
    cmd = [
        str(py),
        "-X",
        "utf8",
        "-m",
        "telelink",
        "ars",
        "run",
        slug,
        contact,
        "--foreground",
    ]

    if sys.platform != "win32":
        subprocess.Popen(cmd, cwd=str(root), env=env)
        return True

    subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        executable=str(py),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return True
