"""Start and stop the notification watcher in a separate console window."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def watcher_pid_file(config: dict | None = None) -> Path:
    if config:
        base = Path(config["output"]["dir"])
    else:
        from telelink.config import load_config

        base = Path(load_config()["output"]["dir"])
    return base / "watcher.pid"


def is_watcher_running(config: dict | None = None) -> bool:
    pid_path = watcher_pid_file(config)
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


def write_watcher_pid() -> None:
    pid_path = watcher_pid_file()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def clear_watcher_pid() -> None:
    watcher_pid_file().unlink(missing_ok=True)


def _win_process_name(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return None


def _win_parent_pid(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    parent: int | None = None
    try:
        if ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.th32ProcessID == pid:
                    parent = int(entry.th32ParentProcessID)
                    break
                if not ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        ctypes.windll.kernel32.CloseHandle(snap)
    return parent if parent else None


def _find_listener_pids() -> set[int]:
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            script = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -and $_.CommandLine -match 'telelink (watcher|listen)' } | "
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
            r = subprocess.run(
                ["pgrep", "-f", "telelink (watcher|listen)"],
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


def _kill_watcher_shells(extra_pids: set[int]) -> int:
    """Force-close TeleLink Watcher console windows (Windows)."""
    if sys.platform != "win32":
        return 0
    closed = 0
    shell_names = {"cmd.exe", "windowsterminal.exe", "pwsh.exe", "powershell.exe"}
    for pid in list(extra_pids):
        parent = _win_parent_pid(pid)
        chain = []
        while parent and parent not in chain:
            chain.append(parent)
            name = _win_process_name(parent)
            if name in shell_names:
                if _kill_pid(parent, force=True):
                    closed += 1
                break
            parent = _win_parent_pid(parent)
    try:
        script = (
            "Get-Process | Where-Object { "
            "$_.MainWindowTitle -and $_.MainWindowTitle -match 'TeleLink Watcher' "
            "} | Stop-Process -Force -ErrorAction SilentlyContinue"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=15,
            check=False,
        )
        closed += 1
    except (OSError, subprocess.TimeoutExpired):
        pass
    return closed


def stop_watcher(*, force: bool = True) -> tuple[bool, str]:
    """Force-stop watcher process(es) and close its console window."""
    from telelink.config import load_config

    config = load_config()
    targets: set[int] = set()

    pid_path = watcher_pid_file(config)
    if pid_path.exists():
        try:
            targets.add(int(pid_path.read_text(encoding="utf-8").strip()))
        except (ValueError, OSError):
            pass

    targets |= _find_listener_pids()
    killed: list[int] = []
    for pid in sorted(targets):
        if _kill_pid(pid, force=force):
            killed.append(pid)

    _kill_watcher_shells(targets)
    clear_watcher_pid()

    if killed:
        return True, f"stopped watcher (pid {', '.join(map(str, killed))})"
    if targets:
        return True, "watcher stopped"
    return False, "no watcher running"


def auto_start_watcher_if_configured(
    *,
    root: Path | None = None,
    config: dict | None = None,
) -> str:
    """Spawn watcher on shell boot when listener.auto_start_window is enabled.

    Returns ``started``, ``running``, ``disabled``, or ``failed``.
    """
    from telelink.config import load_config, watcher_auto_start_enabled

    cfg = config or load_config()
    if not watcher_auto_start_enabled(cfg):
        return "disabled"
    if is_watcher_running(cfg):
        return "running"
    listener = cfg.get("listener") or {}
    delay = float(listener.get("auto_start_delay_seconds") or 0)
    if delay > 0:
        time.sleep(delay)
    root = root or Path.cwd()
    if spawn_watcher_window(root=root, background=True):
        return "started"
    return "failed"


def spawn_watcher_window(
    *,
    root: Path | None = None,
    focus: bool = False,
    background: bool = False,
) -> bool:
    """Launch `telelink watcher` in a new console. Returns False if already running."""
    root = root or Path(__file__).resolve().parent.parent
    py = root / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)

    from telelink.config import load_config

    config = load_config(root / "config.yaml")
    if is_watcher_running(config):
        return False

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["TELELINK_WATCHER"] = "1"
    cmd = [str(py), "-X", "utf8", "-m", "telelink", "watcher", "--foreground"]

    shell_hwnd = None
    if background and sys.platform == "win32" and not focus:
        from telelink.win_console import get_console_hwnd

        shell_hwnd = get_console_hwnd()

    if sys.platform != "win32":
        subprocess.Popen(cmd, cwd=str(root), env=env)
        return True

    subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

    if background and not focus:
        from telelink.win_console import background_watcher_handoff

        background_watcher_handoff(shell_hwnd=shell_hwnd)

    return True
