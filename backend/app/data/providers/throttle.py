"""Client-side request pacing for the vendor adapters.

Every supported vendor sells access by request rate. A full-universe refresh followed by
a scan is thousands of requests, so without pacing the first real API key would spend its
minute budget in a few seconds and the scanner would see a wall of 429s — which it
correctly treats as a data-integrity failure, meaning *no signals at all*.

The limiter is deliberately client-side and conservative: it is cheaper to wait than to
be throttled, and a vendor that answers 429 has already cost a request.

Injectable ``monotonic``/``sleep`` keep the tests instant and deterministic instead of
making them wait on the wall clock.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 60.0


class RateLimiter:
    """Sliding-window limiter: at most ``per_minute`` acquisitions in any 60s window.

    ``per_minute <= 0`` disables pacing entirely, which is what an unmetered enterprise
    plan wants.
    """

    def __init__(
        self,
        per_minute: int,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.per_minute = per_minute
        self._monotonic = monotonic
        self._sleep = sleep
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def acquire(self) -> float:
        """Block until a request may be issued. Returns the seconds spent waiting."""
        if not self.enabled:
            return 0.0

        waited = 0.0
        while True:
            with self._lock:
                now = self._monotonic()
                while self._hits and now - self._hits[0] >= WINDOW_SECONDS:
                    self._hits.popleft()
                if len(self._hits) < self.per_minute:
                    self._hits.append(now)
                    return waited
                # Sleep outside the lock so other threads can drain the window too.
                delay = WINDOW_SECONDS - (now - self._hits[0])
            delay = max(delay, 0.001)
            self._sleep(delay)
            waited += delay
