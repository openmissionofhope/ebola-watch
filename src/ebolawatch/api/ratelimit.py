"""In-process token-bucket rate limiting. For multi-instance deployments, put a
shared limiter (reverse proxy or Redis) in front; this layer remains as a backstop."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int | None = None):
        self.rate = rate_per_minute / 60.0
        self.capacity = burst or max(10, rate_per_minute // 2)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < cost:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - cost, now)
            if len(self._state) > 100_000:
                self._state.clear()
            return True

    def reset(self) -> None:
        with self._lock:
            self._state.clear()
