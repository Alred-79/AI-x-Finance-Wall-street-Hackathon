"""In-process memo for expensive read aggregates.

Entries are keyed by the store's write generation (bumped on every insert/upsert/execute in this process), so any
write invalidates them immediately. A TTL is kept as a safety net for writes made by another process (e.g. the
pre-index CLI against the same Neon database).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..store.db import Store

_lock = threading.Lock()
_entries: dict[str, tuple[int, float, Any]] = {}
DEFAULT_TTL = 60.0


def memo(store: Store, key: str, fn: Callable[[], Any], ttl: float = DEFAULT_TTL) -> Any:
    gen = store.generation
    now = time.time()
    with _lock:
        hit = _entries.get(key)
        if hit and hit[0] == gen and now - hit[1] < ttl:
            return hit[2]
    value = fn()
    with _lock:
        _entries[key] = (gen, now, value)
    return value


def invalidate(prefix: str | None = None) -> None:
    with _lock:
        if prefix is None:
            _entries.clear()
        else:
            for k in [k for k in _entries if k.startswith(prefix)]:
                del _entries[k]
