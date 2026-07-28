from dataclasses import dataclass
from math import pow

from app.core.random_source import RandomSource, SystemRandomSource
from app.targets.base import InvalidTargetConfiguration, TargetExecutionError


@dataclass(frozen=True, slots=True)
class FailureClassification:
    error_code: str
    retryable: bool
    upstream_status_code: int | None
    safe_message: str


@dataclass(frozen=True, slots=True)
class RetryDecision:
    failure: FailureClassification
    should_retry: bool
    backoff_seconds: float | None


def classify_failure(error: BaseException) -> FailureClassification:
    if isinstance(error, TargetExecutionError):
        return FailureClassification(
            error_code=error.code,
            retryable=error.retryable,
            upstream_status_code=error.status_code,
            safe_message=str(error)[:1_000],
        )
    if isinstance(error, TimeoutError):
        return FailureClassification(
            error_code="target_timeout",
            retryable=True,
            upstream_status_code=None,
            safe_message="target request timed out",
        )
    if isinstance(error, InvalidTargetConfiguration):
        return FailureClassification(
            error_code="invalid_target_configuration",
            retryable=False,
            upstream_status_code=None,
            safe_message="target configuration is invalid",
        )
    return FailureClassification(
        error_code="worker_internal_error",
        retryable=False,
        upstream_status_code=None,
        safe_message="worker execution failed",
    )


class RetryPolicy:
    def __init__(
        self,
        *,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        jitter_ratio: float = 0.2,
        random_source: RandomSource | None = None,
    ) -> None:
        if base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError("max_delay_seconds must be at least the base delay")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._jitter_ratio = jitter_ratio
        self._random_source = random_source or SystemRandomSource()

    def decide(
        self,
        failure: FailureClassification,
        *,
        attempt_number: int,
        max_attempts: int,
        cancellation_requested: bool,
    ) -> RetryDecision:
        if attempt_number <= 0 or max_attempts <= 0:
            raise ValueError("attempt counts must be positive")
        should_retry = (
            failure.retryable and attempt_number < max_attempts and not cancellation_requested
        )
        return RetryDecision(
            failure=failure,
            should_retry=should_retry,
            backoff_seconds=(self.backoff_seconds(attempt_number) if should_retry else None),
        )

    def backoff_seconds(self, attempt_number: int) -> float:
        if attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        exponential = min(
            self._max_delay_seconds,
            self._base_delay_seconds * pow(2.0, attempt_number - 1),
        )
        sample = self._random_source.random()
        if not 0 <= sample < 1:
            raise ValueError("random source returned a value outside [0, 1)")
        multiplier = 1 + self._jitter_ratio * ((2 * sample) - 1)
        return max(0.0, exponential * multiplier)
