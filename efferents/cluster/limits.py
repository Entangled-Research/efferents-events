"""Per-key rate limiting for a small multi-user server."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Hashable


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` events per ``window_s`` per key."""

    def __init__(self, limit: int, window_s: float = 60.0, *,
                 clock: Callable[[], float] = time.monotonic):
        self.limit = int(limit)
        self.window_s = float(window_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._events: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> bool:
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self, key: Hashable | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
