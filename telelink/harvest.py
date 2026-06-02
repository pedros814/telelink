from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp"}


def _pkg_roots() -> list[Path]:
    local = Path.home() / "AppData" / "Local" / "Packages"
    roots = list(local.glob("Microsoft.YourPhone_*"))
    roots += list(local.glob("Microsoft.Windows.CrossDevice_*"))
    return [p for p in roots if p.is_dir()]


def find_phone_link_databases() -> list[Path]:
    found: list[Path] = []
    for root in _pkg_roots():
        for db in root.rglob("*.db"):
            name = db.name.lower()
            if any(k in name for k in ("photo", "message", "media", "mms", "chat", "sms")):
                found.append(db)
        # common path even if name differs
        for pattern in (
            "**/photos.db",
            "**/messages.db",
            "**/phone.db",
            "**/Phone.db",
            "**/MediaCache.db",
        ):
            found.extend(root.glob(pattern))
    if not found:
        try:
            from telelink.config import load_config
            from telelink.phone_link_fallback import fallback_find_photos_databases

            found.extend(fallback_find_photos_databases(load_config()))
        except ImportError:
            pass
    return list(dict.fromkeys(found))


def _copy_query_db(src: Path) -> Path:
    """Phone Link may lock DBs - work on a temp copy."""
    tmp = Path(tempfile.gettempdir()) / "telelink" / f"db_{src.name}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, tmp)
    return tmp


def _table_blob_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cols: list[str] = []
    for row in conn.execute(f"PRAGMA table_info({table})"):
        name = row[1]
        ctype = (row[2] or "").upper()
        if "BLOB" in ctype or name.lower() in (
            "thumbnail",
            "thumb",
            "data",
            "image",
            "payload",
            "content",
            "bytes",
        ):
            cols.append(name)
    return cols


def extract_images_from_sqlite(db_path: Path, out_dir: Path) -> list[Path]:
    """Pull image blobs from Phone Link-style SQLite caches."""
    saved: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        work = _copy_query_db(db_path)
    except OSError:
        work = db_path

    try:
        conn = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
    except sqlite3.Error:
        return saved

    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        for table in tables:
            blob_cols = _table_blob_columns(conn, table)
            if not blob_cols:
                continue
            id_cols = [
                r[1]
                for r in conn.execute(f"PRAGMA table_info({table})")
                if r[1].lower() in ("id", "rowid", "photo_id", "message_id")
            ]
            sel = ", ".join(dict.fromkeys(id_cols + blob_cols))
            try:
                cur = conn.execute(f"SELECT {sel} FROM [{table}] LIMIT 500")
                rows = cur.fetchall()
                colnames = [d[0] for d in (cur.description or [])]
            except sqlite3.Error:
                continue
            if not colnames:
                continue
            for row in rows:
                rowd = dict(zip(colnames, row))
                for col in blob_cols:
                    blob = rowd.get(col)
                    if not isinstance(blob, (bytes, memoryview)) or len(blob) < 200:
                        continue
                    raw = bytes(blob)
                    ext = ".jpg"
                    if raw[:8] == b"\x89PNG\r\n\x1a\n":
                        ext = ".png"
                    elif raw[:3] == b"GIF":
                        ext = ".gif"
                    key = hashlib.sha256(raw).hexdigest()[:16]
                    dest = out_dir / f"{db_path.stem}_{table}_{key}{ext}"
                    if dest.exists():
                        continue
                    dest.write_bytes(raw)
                    saved.append(dest)
    finally:
        conn.close()
    return saved


def resolve_ms_appdata(uri: str) -> Path | None:
    """Map ms-appdata:///local/... to UWP package LocalState path."""
    if not uri or "ms-appdata" not in uri.lower():
        return None
    m = re.search(r"local[/\\](.+)$", uri, re.I)
    if not m:
        return None
    rel = m.group(1).replace("/", "\\")
    for root in _pkg_roots():
        candidate = root / "LocalState" / rel
        if candidate.is_file():
            return candidate
        candidate2 = root / rel
        if candidate2.is_file():
            return candidate2
    return None


def extract_images_from_notification_xml(xml: str, out_dir: Path) -> list[Path]:
    saved: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in re.findall(r'<image[^>]+src=["\']([^"\']+)["\']', xml, re.I):
        path = resolve_ms_appdata(src)
        if not path or path.suffix.lower() not in IMAGE_EXT:
            if src.startswith("http"):
                continue
            continue
        key = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        dest = out_dir / f"toast_{key}{path.suffix.lower()}"
        if dest.exists():
            continue
        shutil.copy2(path, dest)
        saved.append(dest)
    return saved


_SKIP_PARTS = (
    "app_icons",
    "app_icon_",
    "badge",
    "favicon",
    "\\icons\\",
    "splash",
)

_KEEP_PARTS = (
    "message",
    "media",
    "photo",
    "mms",
    "attachment",
    "thumb",
    "image",
    "content",
    "transfer",
    "incoming",
    "shared",
)


def _is_message_media(path: Path) -> bool:
    low = str(path).lower()
    if any(s in low for s in _SKIP_PARTS):
        return False
    size = path.stat().st_size
    # Real screenshots/photos are usually > 15KB; icons are tiny
    if size < 12_000 and "thumb" not in low:
        return False
    if any(k in low for k in _KEEP_PARTS):
        return True
    # Large images in TempState often are notification/media payloads
    if "tempstate" in low and size >= 30_000:
        return True
    return False


def scan_package_images(since_mtime: float = 0) -> list[Path]:
    """Likely message/media images inside Phone Link package folders."""
    found: list[Path] = []
    for root in _pkg_roots():
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
                continue
            if since_mtime and p.stat().st_mtime < since_mtime:
                continue
            try:
                if not _is_message_media(p):
                    continue
            except OSError:
                continue
            found.append(p)
    return found


class AutoHarvester:
    """Background grab: Phone Link DB blobs, toast images, package cache files."""

    def __init__(
        self,
        config: dict[str, Any],
        on_file: Callable[[Path], None],
    ) -> None:
        self.config = config
        self.on_file = on_file
        harvest = config.get("harvest", {})
        self.enabled = harvest.get("enabled", True)
        self.poll_seconds = float(harvest.get("poll_seconds", 5))
        self._seen: set[str] = set()
        self._scratch = Path(tempfile.gettempdir()) / "telelink" / "harvest"
        self._scratch.mkdir(parents=True, exist_ok=True)
        self._startup = __import__("time").time()
        self._dbs = find_phone_link_databases()
        self._db_scan_interval = float(harvest.get("db_scan_seconds", 45))
        self._pkg_scan_interval = float(harvest.get("package_scan_seconds", 30))
        self._last_db_scan = 0.0
        self._last_pkg_scan = 0.0
        self._img_watermark = self._startup - 5

    def _emit(self, path: Path) -> None:
        key = hashlib.sha256(path.read_bytes()).hexdigest()
        if key in self._seen:
            return
        self._seen.add(key)
        self.on_file(path)

    def poll_once(self) -> int:
        if not self.enabled:
            return 0
        n = 0
        now = __import__("time").time()
        blob_dir = self._scratch / "blobs"

        if now - self._last_db_scan >= self._db_scan_interval:
            self._last_db_scan = now
            for db in self._dbs:
                for img in extract_images_from_sqlite(db, blob_dir):
                    self._emit(img)
                    n += 1

        if now - self._last_pkg_scan >= self._pkg_scan_interval:
            self._last_pkg_scan = now
            for img in scan_package_images(since_mtime=self._img_watermark):
                self._emit(img)
                n += 1
            self._img_watermark = now - 2
        return n
