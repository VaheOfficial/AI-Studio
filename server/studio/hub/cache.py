"""Tiny thread-safe TTL cache for hub lookups (search pages, repo metadata) so browsing stays snappy and
Hugging Face / ollama.com aren't hit on every keystroke or drawer reopen."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import TypeVar

T = TypeVar("T")

_MAX_ENTRIES = 256
_lock = threading.Lock()
_entries: dict[Hashable, tuple[float, object]] = {}


def cached(key: Hashable, ttl_s: float, compute: Callable[[], T]) -> T:
    now = time.monotonic()
    with _lock:
        hit = _entries.get(key)
        if hit and hit[0] > now:
            return hit[1]  # type: ignore[return-value]
    value = compute()
    with _lock:
        if len(_entries) >= _MAX_ENTRIES:
            for k in sorted(_entries, key=lambda k: _entries[k][0])[: _MAX_ENTRIES // 4]:
                del _entries[k]
        _entries[key] = (now + ttl_s, value)
    return value
