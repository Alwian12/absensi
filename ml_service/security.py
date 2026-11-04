"""Internal service-to-service authentication and rate limiting for the ML service."""
from __future__ import annotations

import hmac
import time
from threading import Lock

from fastapi import Header, HTTPException, status

from app.config import settings


def require_service_token(x_service_token: str = Header(default="")) -> None:
    """Reject requests without the shared internal service token."""
    expected = settings.face_service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FACE_SERVICE_TOKEN belum dikonfigurasi pada layanan ML.",
        )
    if not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token layanan tidak valid.",
        )


class SlidingWindowLimiter:
    """Simple per-key sliding-window rate limiter (per-process)."""

    def __init__(self, max_events: int, window_seconds: float = 60.0) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            recent = [t for t in self._events.get(key, []) if now - t < self.window_seconds]
            if len(recent) >= self.max_events:
                self._events[key] = recent
                return False
            recent.append(now)
            self._events[key] = recent
            return True


face_rate_limiter = SlidingWindowLimiter(max_events=settings.face_service_rate_per_minute)
