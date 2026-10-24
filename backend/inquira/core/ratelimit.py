"""Fixed-window rate limiting with an in-memory or Redis backend.

In-memory is fine for a single instance. Set INQUIRA_REDIS_URL when running
several API replicas so limits are shared.
"""

from __future__ import annotations

import threading
import time

from inquira.core.config import get_settings
from inquira.core.errors import ApiError

_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(rate: str) -> tuple[int, int]:
    count, _, period = rate.partition("/")
    return int(count), _PERIODS[period.strip().rstrip("s")]


class _MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, started = self._hits.get(key, (0, now))
            if now - started >= window:
                count, started = 0, now
            count += 1
            self._hits[key] = (count, started)
            if len(self._hits) > 50_000:  # bound memory under key-spraying
                cutoff = now - 86400
                self._hits = {k: v for k, v in self._hits.items() if v[1] > cutoff}
            return count


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url)

    def hit(self, key: str, window: int) -> int:
        bucket = f"inquira:rl:{key}:{int(time.time() // window)}"
        pipe = self._redis.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window)
        return int(pipe.execute()[0])


_backend: _MemoryBackend | _RedisBackend | None = None


def _get_backend() -> _MemoryBackend | _RedisBackend:
    global _backend
    if _backend is None:
        url = get_settings().redis_url
        _backend = _RedisBackend(url) if url else _MemoryBackend()
    return _backend


def enforce(scope: str, identity: str, rate: str) -> None:
    limit, window = parse_rate(rate)
    if _get_backend().hit(f"{scope}:{identity}", window) > limit:
        raise ApiError(429, "rate_limited", "Too many requests. Please slow down and try again shortly.")
