from __future__ import annotations

from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any, Callable, Hashable


class TtlResponseCache:
    """Small process-local TTL cache for expensive, shared API payloads."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        self._lock = Lock()

    def get_or_create(
        self,
        key: Hashable,
        *,
        ttl_seconds: float,
        factory: Callable[[], Any],
    ) -> Any:
        with self._lock:
            now = self._clock()
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return deepcopy(cached[1])

            value = factory()
            self._entries[key] = (now + max(0.0, ttl_seconds), deepcopy(value))
            return deepcopy(value)

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()


__all__ = ["TtlResponseCache"]
