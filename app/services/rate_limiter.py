import time
from threading import Lock


class SimpleRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
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


# Module-level singleton
login_rate_limiter = SimpleRateLimiter(max_attempts=5, window_seconds=900)
