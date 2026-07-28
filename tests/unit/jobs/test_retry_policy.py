import pytest

from app.jobs.retry_policy import RetryPolicy, classify_failure
from app.targets.base import (
    InvalidTargetConfiguration,
    TargetHTTPError,
    TargetTimeoutError,
)


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503, 504])
def test_transient_http_failures_are_retryable(status_code: int) -> None:
    failure = classify_failure(TargetHTTPError(status_code))

    assert failure.retryable is True
    assert failure.error_code == f"target_http_{status_code}"
    assert failure.upstream_status_code == status_code


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_permanent_http_failures_are_not_retryable(status_code: int) -> None:
    assert classify_failure(TargetHTTPError(status_code)).retryable is False


def test_timeout_is_retryable_but_invalid_configuration_is_permanent() -> None:
    assert classify_failure(TargetTimeoutError()).retryable is True
    assert classify_failure(InvalidTargetConfiguration("invalid")).retryable is False


def test_exponential_backoff_uses_injected_jitter_without_sleep() -> None:
    policy = RetryPolicy(
        base_delay_seconds=2,
        max_delay_seconds=60,
        jitter_ratio=0.25,
        random_source=FixedRandom(0.75),
    )

    decision = policy.decide(
        classify_failure(TargetHTTPError(503)),
        attempt_number=3,
        max_attempts=5,
        cancellation_requested=False,
    )

    assert decision.should_retry is True
    assert decision.backoff_seconds == 9.0


def test_retry_stops_at_max_attempts_or_after_cancellation() -> None:
    policy = RetryPolicy(random_source=FixedRandom(0.5))
    failure = classify_failure(TargetHTTPError(503))

    exhausted = policy.decide(
        failure,
        attempt_number=3,
        max_attempts=3,
        cancellation_requested=False,
    )
    cancelled = policy.decide(
        failure,
        attempt_number=1,
        max_attempts=3,
        cancellation_requested=True,
    )

    assert exhausted.should_retry is False
    assert cancelled.should_retry is False
    assert exhausted.backoff_seconds is None
