"""Polite outbound HTTP: identified user agent, per-host rate limits, bounded
retries with backoff (honouring Retry-After), and response-size caps.

Connectors never send credentials anywhere other than the service they belong
to, and never attempt to bypass access controls: a 401/403 is reported as
"unavailable", not retried with workarounds.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import get_settings

MAX_BYTES = 25 * 1024 * 1024


class SourceUnavailable(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class HostPolicy:
    min_interval_s: float = 1.0


DEFAULT_HOST_POLICIES = {
    "api.gdeltproject.org": HostPolicy(6.0),  # GDELT asks for <= 1 request / 5 s
    "overpass-api.de": HostPolicy(10.0),
    "www.who.int": HostPolicy(2.0),
    "data.humdata.org": HostPolicy(2.0),
    "api.worldbank.org": HostPolicy(1.0),
}


class HttpClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        s = get_settings()
        self._client = httpx.Client(
            headers={"User-Agent": s.user_agent, "Accept": "application/json, text/csv, application/xml;q=0.9, */*;q=0.5"},
            timeout=s.http_timeout_s,
            follow_redirects=True,
            transport=transport,
        )
        self._max_retries = s.http_max_retries
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._sleep = sleep

    def _throttle(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        policy = DEFAULT_HOST_POLICIES.get(host, HostPolicy())
        with self._lock:
            wait = policy.min_interval_s - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                self._sleep(wait)
            self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle(url)
            try:
                r = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as e:  # network failure
                last_exc = e
                if attempt < self._max_retries:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise SourceUnavailable(f"network error: {e.__class__.__name__}") from e
            if r.status_code in (401, 403):
                raise SourceUnavailable(f"access denied by source (HTTP {r.status_code}); not bypassed", r.status_code)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < self._max_retries:
                    retry_after = r.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                    self._sleep(min(wait, 60.0))
                    delay *= 2
                    continue
                kind = "rate limited" if r.status_code == 429 else "server error"
                raise SourceUnavailable(f"{kind} (HTTP {r.status_code}) after {attempt + 1} attempts", r.status_code)
            if r.status_code >= 400:
                raise SourceUnavailable(f"HTTP {r.status_code}", r.status_code)
            if len(r.content) > MAX_BYTES:
                raise SourceUnavailable("response exceeds size limit")
            return r
        raise SourceUnavailable(f"request failed: {last_exc}")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs):
        r = self.get(url, **kwargs)
        try:
            return r.json()
        except ValueError as e:
            raise SourceUnavailable("source returned non-JSON content") from e

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()
