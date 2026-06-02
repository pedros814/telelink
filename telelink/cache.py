"""In-memory TTL cache with optional localStorage backing."""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        row = self._entries.get(key)
        if not row:
            return None
        expires, value = row
        if time.monotonic() > expires:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (time.monotonic() + self.ttl_seconds, value)

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value)
        return value

    def invalidate(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._entries.clear()
            return
        for key in list(self._entries):
            if key.startswith(prefix):
                del self._entries[key]
