"""Testes de limits.py com relogio falso."""

from ga4_sql_analyst.limits import (
    REASON_DAILY_QUOTA,
    REASON_RATE_LIMITED,
    SECONDS_PER_DAY,
    WINDOW_SECONDS,
    LimitDecision,
    StrictRateLimiter,
)

START = 3 * SECONDS_PER_DAY + 1_000.0
IP = "203.0.113.7"


class FakeClock:
    """Clock whose time only moves when the test says so."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _limiter(
    clock: FakeClock,
    rate_per_minute: int = 5,
    daily_requests: int = 1_000,
    daily_llm_calls: int = 1_000,
) -> StrictRateLimiter:
    return StrictRateLimiter(
        rate_per_minute=rate_per_minute,
        daily_requests=daily_requests,
        daily_llm_calls=daily_llm_calls,
        clock=clock,
    )


def test_allows_up_to_rate_then_blocks_with_retry_after() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock)
    for _ in range(5):
        assert limiter.check_request(IP) == LimitDecision(True, None, 0)
    blocked = limiter.check_request(IP)
    assert blocked == LimitDecision(False, REASON_RATE_LIMITED, WINDOW_SECONDS)


def test_window_slides_and_allows_again_after_sixty_seconds() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.check_request(IP)
    clock.now = START + 30
    assert limiter.check_request(IP) == LimitDecision(False, REASON_RATE_LIMITED, 30)
    clock.now = START + WINDOW_SECONDS
    assert limiter.check_request(IP).is_allowed is True


def test_retry_after_rounds_up_to_whole_seconds() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=1)
    limiter.check_request(IP)
    clock.now = START + 10.4
    assert limiter.check_request(IP) == LimitDecision(False, REASON_RATE_LIMITED, 50)


def test_limits_are_per_ip() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=1)
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.check_request("198.51.100.1").is_allowed is True
    assert limiter.check_request(IP).reason == REASON_RATE_LIMITED


def test_daily_quota_blocks_with_seconds_to_midnight_utc() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=100, daily_requests=3)
    for _ in range(3):
        assert limiter.check_request(IP).is_allowed is True
    blocked = limiter.check_request("198.51.100.1")
    assert blocked == LimitDecision(False, REASON_DAILY_QUOTA, SECONDS_PER_DAY - 1_000)


def test_daily_quota_is_checked_before_ip_window() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=2, daily_requests=2)
    limiter.check_request(IP)
    limiter.check_request(IP)
    assert limiter.check_request(IP).reason == REASON_DAILY_QUOTA


def test_denied_requests_are_not_recorded() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=1, daily_requests=2)
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.check_request(IP).reason == REASON_RATE_LIMITED
    clock.now = START + WINDOW_SECONDS
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.check_request(IP).reason == REASON_DAILY_QUOTA


def test_day_rollover_resets_request_counters_and_ip_table() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, rate_per_minute=1, daily_requests=1)
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.check_request(IP).reason == REASON_DAILY_QUOTA
    clock.now = START + SECONDS_PER_DAY
    assert limiter.check_request(IP).is_allowed is True


def test_ip_is_stored_only_as_hash() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock)
    limiter.check_request(IP)
    assert IP not in limiter._hits
    assert len(limiter._hits) == 1
    (key,) = limiter._hits
    assert len(key) == 16
    assert all(char in "0123456789abcdef" for char in key)
    assert IP not in key


def test_llm_calls_consumed_until_limit() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, daily_llm_calls=2)
    assert limiter.try_consume_llm_call() is True
    assert limiter.try_consume_llm_call() is True
    assert limiter.try_consume_llm_call() is False
    assert limiter.try_consume_llm_call() is False


def test_llm_calls_reset_on_day_rollover() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, daily_llm_calls=1)
    assert limiter.try_consume_llm_call() is True
    assert limiter.try_consume_llm_call() is False
    clock.now = START + SECONDS_PER_DAY
    assert limiter.try_consume_llm_call() is True


def test_llm_budget_is_independent_of_request_quota() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, daily_requests=1, daily_llm_calls=1)
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.try_consume_llm_call() is True


def test_same_day_does_not_reset_llm_counter() -> None:
    clock = FakeClock(START)
    limiter = _limiter(clock, daily_llm_calls=1)
    assert limiter.try_consume_llm_call() is True
    clock.now = START + 60
    assert limiter.check_request(IP).is_allowed is True
    assert limiter.try_consume_llm_call() is False
