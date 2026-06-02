"""Scoped filesystem fallback when primary Phone Link path globs miss."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from telelink.harvest import _pkg_roots

log = logging.getLogger(__name__)

_PHONE_DB_NAMES = ("phone.db", "Phone.db", "messages.db", "Messages.db")

_PACKAGE_PREFIXES = (
    "microsoft.yourphone_",
    "microsoft.windows.crossdevice_",
)


def _fallback_settings(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        from telelink.config import load_config

        config = load_config()
    phone_link = config.get("phone_link") or {}
    # Support legacy phone_link.search from older configs.
    fb = phone_link.get("fallback") or phone_link.get("search") or {}
    return {
        "enabled": fb.get("enabled", True),
        "engine": str(fb.get("engine", "powershell")).strip().lower(),
        "packages_wide": fb.get("packages_wide", fb.get("allow_packages_wide_search", True)),
        "timeout_seconds": float(fb.get("timeout_seconds", 30)),
        "max_results": int(fb.get("max_results", 20)),
    }


def _subprocess_flags() -> int:
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _packages_parent() -> Path:
    return Path.home() / "AppData" / "Local" / "Packages"


def _is_phone_link_package_dir(name: str) -> bool:
    low = name.lower()
    return low.startswith(_PACKAGE_PREFIXES)


def _discover_package_roots(*, wide: bool) -> list[Path]:
    roots = _pkg_roots()
    if roots:
        return roots
    if not wide:
        return []
    parent = _packages_parent()
    if not parent.is_dir():
        return []
    found: list[Path] = []
    try:
        for entry in parent.iterdir():
            if entry.is_dir() and _is_phone_link_package_dir(entry.name):
                found.append(entry.resolve())
    except OSError as exc:
        log.debug("Packages scan failed: %s", exc)
    return found


def _is_phone_link_db_path(path: Path, db_name: str) -> bool:
    try:
        text = str(path.resolve())
    except OSError:
        text = str(path)
    normalized = text.replace("/", "\\").lower()
    if "yourphone" not in normalized and "crossdevice" not in normalized:
        return False
    if r"\system\database" not in normalized:
        return False
    return path.name.lower() == db_name.lower()


def _is_recent_photos_folder(path: Path) -> bool:
    try:
        text = str(path.resolve())
    except OSError:
        text = str(path)
    normalized = text.replace("/", "\\").lower()
    if "yourphone" not in normalized and "crossdevice" not in normalized:
        return False
    if r"\localcache\indexed" not in normalized:
        return False
    return path.name.lower() == "recent photos"


def _is_downloads_phone_link_folder(path: Path) -> bool:
    try:
        text = str(path.resolve())
    except OSError:
        text = str(path)
    normalized = text.replace("/", "\\").lower()
    downloads = str((Path.home() / "Downloads").resolve()).replace("/", "\\").lower()
    return normalized.startswith(downloads) and path.name.lower() == "phone link"


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _powershell_find(
    roots: list[Path],
    *,
    file_name: str | None = None,
    dir_name: str | None = None,
    path_predicate: Callable[[Path], bool],
    timeout: float,
    max_results: int,
) -> list[Path]:
    """Terminal fallback via PowerShell Get-ChildItem (built-in on Windows)."""
    if not roots:
        return []

    found: list[Path] = []
    deadline = time.monotonic() + max(1.0, timeout)
    filter_name = file_name or dir_name or ""
    item_type = "Container" if dir_name else "Leaf"

    for root in roots:
        if time.monotonic() >= deadline:
            break
        root_ps = str(root).replace("'", "''")
        name_ps = filter_name.replace("'", "''")
        if dir_name:
            script = (
                f"Get-ChildItem -LiteralPath '{root_ps}' -Recurse "
                f"-Filter '{name_ps}' -Directory -ErrorAction SilentlyContinue | "
                f"Select-Object -First {max_results} -ExpandProperty FullName"
            )
        else:
            script = (
                f"Get-ChildItem -LiteralPath '{root_ps}' -Recurse "
                f"-Filter '{name_ps}' -File -ErrorAction SilentlyContinue | "
                f"Select-Object -First {max_results} -ExpandProperty FullName"
            )
        try:
            proc = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=max(1.0, deadline - time.monotonic()),
                check=False,
                creationflags=_subprocess_flags(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.debug("PowerShell fallback failed under %s: %s", root, exc)
            continue

        if proc.returncode != 0 and not (proc.stdout or "").strip():
            log.debug(
                "PowerShell fallback exit %s: %s",
                proc.returncode,
                (proc.stderr or proc.stdout or "").strip(),
            )
            continue

        for line in (proc.stdout or "").splitlines():
            text = line.strip()
            if not text:
                continue
            path = Path(text)
            try:
                ok = path.is_dir() if dir_name else path.is_file()
            except OSError:
                ok = False
            if not ok or not path_predicate(path):
                continue
            found.append(path)
            if len(found) >= max_results:
                return _dedupe_paths(found)

    return _dedupe_paths(found)


def _python_find(
    roots: list[Path],
    *,
    file_name: str | None = None,
    dir_name: str | None = None,
    path_predicate: Callable[[Path], bool],
    timeout: float,
    max_results: int,
) -> list[Path]:
    """In-process scoped walk under Phone Link package roots."""
    found: list[Path] = []
    deadline = time.monotonic() + max(1.0, timeout)
    target_name = (file_name or dir_name or "").lower()

    for root in roots:
        if time.monotonic() >= deadline or len(found) >= max_results:
            break
        try:
            for path in root.rglob("*"):
                if time.monotonic() >= deadline or len(found) >= max_results:
                    break
                if path.name.lower() != target_name:
                    continue
                try:
                    ok = path.is_dir() if dir_name else path.is_file()
                except OSError:
                    continue
                if not ok or not path_predicate(path):
                    continue
                found.append(path)
        except OSError as exc:
            log.debug("Python fallback walk failed under %s: %s", root, exc)

    return _dedupe_paths(found)


def _find_paths(
    *,
    config: dict[str, Any] | None,
    file_name: str | None = None,
    dir_name: str | None = None,
    path_predicate: Callable[[Path], bool],
    extra_roots: list[Path] | None = None,
) -> list[Path]:
    settings = _fallback_settings(config)
    if not settings["enabled"]:
        return []

    roots = _discover_package_roots(wide=settings["packages_wide"])
    if extra_roots:
        roots = _dedupe_paths(roots + [p for p in extra_roots if p.exists()])

    if not roots:
        return []

    engine = settings["engine"]
    if engine in ("off", "false", "none", "disabled"):
        return []

    kwargs = {
        "file_name": file_name,
        "dir_name": dir_name,
        "path_predicate": path_predicate,
        "timeout": settings["timeout_seconds"],
        "max_results": settings["max_results"],
    }

    if engine == "python":
        return _python_find(roots, **kwargs)
    return _powershell_find(roots, **kwargs)


def _fallback_enabled(config: dict[str, Any] | None) -> bool:
    settings = _fallback_settings(config)
    if not settings["enabled"]:
        return False
    engine = settings["engine"]
    if engine in ("off", "false", "none", "disabled"):
        return False
    return True


def fallback_find_contacts_databases(config: dict[str, Any] | None = None) -> list[Path]:
    if not _fallback_enabled(config):
        return []
    log.info("Filesystem fallback: searching for contacts.db")
    return _find_paths(
        config=config,
        file_name="contacts.db",
        path_predicate=lambda p: _is_phone_link_db_path(p, "contacts.db"),
    )


def fallback_find_phone_databases(config: dict[str, Any] | None = None) -> list[Path]:
    if not _fallback_enabled(config):
        return []
    log.info("Filesystem fallback: searching for phone/message databases")
    found: list[Path] = []
    for db_name in _PHONE_DB_NAMES:
        found.extend(
            _find_paths(
                config=config,
                file_name=db_name,
                path_predicate=lambda p, name=db_name: _is_phone_link_db_path(p, name),
            )
        )
    return _dedupe_paths(found)


def fallback_find_calling_databases(config: dict[str, Any] | None = None) -> list[Path]:
    if not _fallback_enabled(config):
        return []
    log.info("Filesystem fallback: searching for calling.db")
    return _find_paths(
        config=config,
        file_name="calling.db",
        path_predicate=lambda p: _is_phone_link_db_path(p, "calling.db"),
    )


def fallback_find_photos_databases(config: dict[str, Any] | None = None) -> list[Path]:
    if not _fallback_enabled(config):
        return []
    log.info("Filesystem fallback: searching for photos.db")
    return _find_paths(
        config=config,
        file_name="photos.db",
        path_predicate=lambda p: _is_phone_link_db_path(p, "photos.db"),
    )


def fallback_find_media_folders(config: dict[str, Any] | None = None) -> list[str]:
    if not _fallback_enabled(config):
        return []

    log.info("Filesystem fallback: searching for Phone Link media folders")
    folders: list[str] = []
    seen: set[str] = set()

    for path in _find_paths(
        config=config,
        dir_name="Recent Photos",
        path_predicate=_is_recent_photos_folder,
    ):
        key = str(path)
        if key not in seen:
            seen.add(key)
            folders.append(key)

    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        for path in _find_paths(
            config=config,
            dir_name="Phone Link",
            path_predicate=_is_downloads_phone_link_folder,
            extra_roots=[downloads],
        ):
            key = str(path)
            if key not in seen:
                seen.add(key)
                folders.append(key)

    return folders


def fallback_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Diagnostics for config/doctor."""
    settings = _fallback_settings(config)
    engine = settings["engine"]
    enabled = settings["enabled"] and engine not in ("off", "false", "none", "disabled")
    if not enabled:
        label = "disabled"
    elif engine == "python":
        label = "python (scoped walk)"
    else:
        label = "powershell (scoped scan)"
    roots = _discover_package_roots(wide=settings["packages_wide"])
    return {
        "enabled": enabled,
        "engine": engine,
        "label": label,
        "package_roots": len(roots),
        "packages_wide": settings["packages_wide"],
        "timeout_seconds": settings["timeout_seconds"],
        "max_results": settings["max_results"],
    }


# Legacy alias used by older call sites during transition.
search_status = fallback_status
