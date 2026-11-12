"""Slow down password guessing.

Counts *failed* attempts per key in a sliding window, in memory. That is
enough while the API runs as a single process; with more than one replica the
counts would need to live somewhere shared (Redis, the database).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

_MAX_KEYS = 10_000


class FailureThrottle:
    """Allow `limit` failures per `window_s` seconds for each key."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        cutoff = self._clock() - self.window_s
        hits = self._failures.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            self._failures.pop(key, None)
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until this key may try again; 0 when it may try now."""
        hits = self._recent(key)
        if len(hits) < self.limit:
            return 0
        return max(1, int(hits[0] + self.window_s - self._clock()) + 1)

    def fail(self, key: str) -> None:
        if len(self._failures) >= _MAX_KEYS:  # bound memory under a spray of made-up keys
            for stale in [k for k in self._failures if not self._recent(k)]:
                self._failures.pop(stale, None)
            if len(self._failures) >= _MAX_KEYS:
                self._failures.pop(next(iter(self._failures)))
        self._failures.setdefault(key, deque()).append(self._clock())

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)

    def reset(self) -> None:
        self._failures.clear()
