"""Rate limiting for login and biometric endpoints (audit finding F-22).

Two implementations share one interface (``is_blocked`` / ``record_attempt`` /
``remaining_seconds`` / ``reset``):

* ``SimpleRateLimiter`` — in-memory, per-process. Used by unit tests.
* ``DatabaseRateLimiter`` — persists events in the ``rate_limit_event`` table so
  limits survive restarts and apply across multiple workers.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import text

from app.config import settings
from app.database import engine


class SimpleRateLimiter:
    """In-memory sliding-window limiter (single process only)."""

    def __init__(self, max_attempts: int = 5, window_seconds: float = 60.0) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = float(window_seconds)
        self._store: dict[str, list[float]] = {}
        self._lock = Lock()

    def _clean(self, key: str, now: float) -> list[float]:
        return [t for t in self._store.get(key, []) if now - t < self.window_seconds]

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._clean(key, time.time())) >= self.max_attempts

    def record_attempt(self, key: str) -> None:
        with self._lock:
            now = time.time()
            attempts = self._clean(key, now)
            attempts.append(now)
            self._store[key] = attempts

    def remaining_seconds(self, key: str) -> int:
        with self._lock:
            now = time.time()
            attempts = self._clean(key, now)
            if not attempts or len(attempts) < self.max_attempts:
                return 0
            return max(0, int(self.window_seconds - (now - attempts[0])))

    def reset(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


class DatabaseRateLimiter:
    """Sliding-window limiter backed by the ``rate_limit_event`` table."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    def _cutoff(self) -> datetime:
        return datetime.now() - timedelta(seconds=self.window_seconds)

    def _count(self, key: str) -> int:
        with engine.begin() as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM rate_limit_event "
                        "WHERE bucket_key = :key AND created_at >= :cutoff"
                    ),
                    {"key": key, "cutoff": self._cutoff()},
                ).scalar()
                or 0
            )

    def is_blocked(self, key: str) -> bool:
        return self._count(key) >= self.max_attempts

    def record_attempt(self, key: str) -> None:
        with engine.begin() as conn:
            # Housekeeping: drop this bucket's expired rows so the table stays small.
            conn.execute(
                text("DELETE FROM rate_limit_event WHERE bucket_key = :key AND created_at < :cutoff"),
                {"key": key, "cutoff": self._cutoff()},
            )
            conn.execute(
                text("INSERT INTO rate_limit_event (bucket_key, created_at) VALUES (:key, :now)"),
                {"key": key, "now": datetime.now()},
            )

    def remaining_seconds(self, key: str) -> int:
        with engine.begin() as conn:
            oldest = conn.execute(
                text(
                    "SELECT MIN(created_at) FROM rate_limit_event "
                    "WHERE bucket_key = :key AND created_at >= :cutoff"
                ),
                {"key": key, "cutoff": self._cutoff()},
            ).scalar()
        if oldest is None or self._count(key) < self.max_attempts:
            return 0
        elapsed = (datetime.now() - oldest).total_seconds()
        return max(0, int(self.window_seconds - elapsed))

    def reset(self, key: str) -> None:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_event WHERE bucket_key = :key"), {"key": key})


def _build_login_limiter() -> SimpleRateLimiter | DatabaseRateLimiter:
    if settings.rate_limit_persistent:
        return DatabaseRateLimiter(max_attempts=5, window_seconds=900)
    return SimpleRateLimiter(max_attempts=5, window_seconds=900)


# Login lockout: 5 failures per 15 minutes (per IP and per identifier).
login_rate_limiter = _build_login_limiter()

# Biometric endpoints: cap the request *rate* (not only failures), per user and IP.
face_user_rate_limiter = SimpleRateLimiter(
    max_attempts=settings.face_rate_per_user_per_minute, window_seconds=60
)
face_ip_rate_limiter = SimpleRateLimiter(
    max_attempts=settings.face_rate_per_ip_per_minute, window_seconds=60
)
