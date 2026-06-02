from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from telelink.models import MessageEvent

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff"}


class ImageHandler(FileSystemEventHandler):
    def __init__(
        self,
        watch_root: Path,
        on_image: Callable[[MessageEvent], None],
        debounce_seconds: float = 1.5,
    ) -> None:
        self.watch_root = watch_root
        self.on_image = on_image
        self.debounce_seconds = debounce_seconds
        self._pending: dict[str, float] = {}

    def _should_handle(self, path: Path) -> bool:
        if path.suffix.lower() not in IMAGE_EXT:
            return False
        if not path.is_file():
            return False
        key = str(path.resolve())
        now = time.time()
        last = self._pending.get(key, 0)
        if now - last < self.debounce_seconds:
            return False
        self._pending[key] = now
        return True

    def _emit(self, path: Path) -> None:
        if self._should_handle(path):
            self.on_image(
                MessageEvent(
                    sender_display="",
                    body="",
                    source="folder_watch",
                    watch_folder=str(self.watch_root),
                    file_path=path,
                )
            )

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._emit(Path(event.src_path))

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        self._emit(Path(event.src_path))


def start_folder_watchers(
    config: dict[str, Any],
    on_image: Callable[[MessageEvent], None],
    *,
    log: Callable[..., None] | None = None,
) -> Observer:
    from telelink import pretty

    def _emit(msg: str) -> None:
        if log is not None:
            log(pretty.info, "WATCH", msg)
        else:
            print(f"[telelink] {msg}", flush=True)

    observer = Observer()
    debounce = float(config.get("media", {}).get("debounce_seconds", 1.5))
    scheduled = 0
    for folder in config.get("phone_link", {}).get("watch_folders", []):
        p = Path(folder)
        if p.exists():
            handler = ImageHandler(p, on_image, debounce_seconds=debounce)
            observer.schedule(handler, str(p), recursive=True)
            scheduled += 1
            _emit(f"watching {p}")
        else:
            _emit(f"skip missing folder: {p}")
    if scheduled == 0:
        _emit("no image folders found — run: telelink config")
    observer.start()
    return observer
