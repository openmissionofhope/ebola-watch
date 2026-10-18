"""Defence against reconstruction of suppressed values through repeated querying.

Public endpoints only serve precomputed aggregates at fixed resolutions, so
filters cannot carve out arbitrary small populations. As an additional layer,
this guard counts the distinct filter combinations each client requests within
a time window; clients that enumerate many combinations (a typical differencing
pattern) are throttled and the event is audit-logged.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque

from ..config import get_settings


class QueryGuard:
    def __init__(self, window_s: int | None = None, max_distinct: int | None = None):
        s = get_settings()
        self.window_s = window_s or s.query_guard_window_s
        self.max_distinct = max_distinct or s.query_guard_max_distinct_filters
        self._seen: dict[str, deque[tuple[float, str]]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(endpoint: str, params: dict) -> str:
        norm = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
        return hashlib.sha256(f"{endpoint}?{norm}".encode()).hexdigest()[:16]

    def check(self, client_id: str, endpoint: str, params: dict) -> bool:
        """Record a query; return False if the client exceeded the distinct-filter budget."""
        now = time.monotonic()
        fp = self.fingerprint(endpoint, params)
        with self._lock:
            q = self._seen[client_id]
            while q and now - q[0][0] > self.window_s:
                q.popleft()
            distinct = {f for _, f in q}
            if fp not in distinct and len(distinct) >= self.max_distinct:
                return False
            q.append((now, fp))
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()
