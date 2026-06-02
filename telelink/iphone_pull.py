from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _have_pymobile() -> bool:
    try:
        import pymobiledevice3  # noqa: F401

        return True
    except ImportError:
        return False


def list_devices() -> list[dict[str, str]]:
    if not _have_pymobile():
        return []
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return [{"raw": ln} for ln in lines]
    except Exception:
        return []


def pull_dcim_photos(
    dest: Path,
    *,
    since_count: int = 0,
) -> list[Path]:
    """
    Pull recent photos from iPhone Camera Roll over USB/Wi-Fi.
    Requires: pip install pymobiledevice3, iPhone trusted, Wi-Fi sync optional.
    """
    if not _have_pymobile():
        return []
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    try:
        # AFC pull from DCIM - common path for saved screenshots/photos
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pymobiledevice3",
                "afc",
                "pull",
                "/DCIM",
                str(dest),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        for p in sorted(dest.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".heic"}:
                saved.append(p)
                if len(saved) >= 50:
                    break
    except Exception:
        pass
    return saved


class IPhonePuller:
    """Optional: pull Camera Roll over network/USB via pymobiledevice3."""

    def __init__(
        self,
        config: dict[str, Any],
        on_file: Callable[[Path], None],
    ) -> None:
        self.config = config
        self.on_file = on_file
        pull = config.get("iphone_pull", {})
        self.enabled = pull.get("enabled", False)
        self.poll_seconds = float(pull.get("poll_seconds", 60))
        self._seen: set[str] = set()
        self._dest = Path(config["output"]["dir"]) / "iphone_pull_cache"

    def poll_once(self) -> int:
        if not self.enabled:
            return 0
        if not _have_pymobile():
            return 0
        n = 0
        for path in pull_dcim_photos(self._dest):
            key = hashlib.sha256(path.read_bytes()).hexdigest()
            if key in self._seen:
                continue
            self._seen.add(key)
            self.on_file(path)
            n += 1
        return n
