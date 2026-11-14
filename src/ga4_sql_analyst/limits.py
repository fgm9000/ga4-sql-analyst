"""In-memory request and LLM-call limits (RNF-04, ADR 002).

Counters live in process memory: they reset when the instance restarts and are not shared
between instances. That is acceptable for a single-instance demo deployment.
"""

import hashlib
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]

WINDOW_SECONDS = 60
SECONDS_PER_DAY = 86_400
IP_HASH_CHARS = 16
REASON_RATE_LIMITED = "rate_limited"
REASON_DAILY_QUOTA = "daily_quota"


@dataclass(frozen=True)
class LimitDecision:
    """Outcome of a request check. retry_after_seconds is 0 when the request is allowed."""

    is_allowed: bool
    reason: str | None
    retry_after_seconds: int


def _hash_ip(client_ip: str) -> str:
    """Return a truncated SHA-256 digest so the raw IP is never stored."""
    return hashlib.sha256(client_ip.encode()).hexdigest()[:IP_HASH_CHARS]


def _retry_after(seconds: float) -> int:
    """Round a wait up to whole seconds, with a minimum of one second."""
    return max(1, math.ceil(seconds))


class StrictRateLimiter:
    """Sliding per-IP window plus a global daily request quota and a daily LLM-call quota."""

    def __init__(
        self,
        rate_per_minute: int,
        daily_requests: int,
        daily_llm_calls: int,
        clock: Clock = time.time,
    ) -> None:
        self._rate_per_minute = rate_per_minute
        self._daily_requests = daily_requests
        self._daily_llm_calls = daily_llm_calls
        self._clock = clock
        self._day = -1
        self._requests_today = 0
        self._llm_calls_today = 0
        self._hits: dict[str, deque[float]] = {}

    def check_request(self, client_ip: str) -> LimitDecision:
        """Check the global daily quota, then the per-IP window; record only allowed requests."""
        now = self._clock()
        self._roll_day(now)
        if self._requests_today >= self._daily_requests:
            seconds_to_midnight = SECONDS_PER_DAY - (now % SECONDS_PER_DAY)
            return LimitDecision(False, REASON_DAILY_QUOTA, _retry_after(seconds_to_midnight))
        hits = self._hits.setdefault(_hash_ip(client_ip), deque())
        while hits and hits[0] <= now - WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self._rate_per_minute:
            return LimitDecision(
                False, REASON_RATE_LIMITED, _retry_after(hits[0] + WINDOW_SECONDS - now)
            )
        hits.append(now)
        self._requests_today += 1
        return LimitDecision(True, None, 0)

    def try_consume_llm_call(self) -> bool:
        """Consume one LLM call from the daily budget; return False if exhausted (no consume)."""
        self._roll_day(self._clock())
        if self._llm_calls_today >= self._daily_llm_calls:
            return False
        self._llm_calls_today += 1
        return True

    def _roll_day(self, now: float) -> None:
        """Reset every counter and the per-IP table when the UTC day changes."""
        day = int(now // SECONDS_PER_DAY)
        if day == self._day:
            return
        self._day = day
        self._requests_today = 0
        self._llm_calls_today = 0
        self._hits.clear()
