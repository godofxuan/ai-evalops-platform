import asyncio
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.evaluation import (
    EvaluationCase,
    ExecutionContext,
    TargetResult,
    TokenUsage,
)
from app.targets.base import (
    InvalidTargetConfiguration,
    TargetCancelledError,
    TargetExecutionError,
    TargetHTTPError,
    TargetInvalidResponseError,
    TargetTimeoutError,
)


class Sleeper(Protocol):
    async def sleep(self, delay_seconds: float) -> None:
        """Wait for a duration."""


class AsyncIOSleeper:
    async def sleep(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)


class MockTargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fixed_delay_ms: int = Field(default=0, ge=0, le=300_000)
    profile: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    outcome: Literal[
        "success",
        "timeout",
        "http_429",
        "http_500",
        "invalid_json",
        "permanent_failure",
    ] = "success"
    fail_until_attempt: int = Field(default=0, ge=0, le=10)
    answer: str = "mock answer"
    citations: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class MockTarget:
    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        sleeper: Sleeper | None = None,
    ) -> None:
        try:
            self._config = MockTargetConfig.model_validate(dict(config))
        except ValidationError as error:
            raise InvalidTargetConfiguration("invalid mock target configuration") from error
        self._sleeper = sleeper or AsyncIOSleeper()

    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        config = self._case_config(case)
        _raise_if_cancelled(context)
        if config.fixed_delay_ms:
            await self._sleeper.sleep(config.fixed_delay_ms / 1_000)
        _raise_if_cancelled(context)

        if context.attempt_number <= config.fail_until_attempt:
            raise TargetHTTPError(503)
        if config.outcome == "timeout":
            raise TargetTimeoutError
        if config.outcome == "http_429":
            raise TargetHTTPError(429)
        if config.outcome == "http_500":
            raise TargetHTTPError(500)
        if config.outcome == "invalid_json":
            raise TargetInvalidResponseError("target_invalid_json")
        if config.outcome == "permanent_failure":
            raise TargetExecutionError(
                "target_permanent_failure",
                "deterministic permanent mock failure",
                retryable=False,
            )
        return TargetResult(
            answer=config.answer,
            citations=tuple(dict(item) for item in config.citations),
            sources=tuple(dict(item) for item in config.sources),
            trace=dict(config.trace),
            token_usage=TokenUsage(
                input_tokens=config.input_tokens,
                output_tokens=config.output_tokens,
            ),
            latency_ms=config.fixed_delay_ms,
        )

    def _case_config(self, case: EvaluationCase) -> MockTargetConfig:
        config = self._config.model_dump()
        profiles = case.metadata.get("mock_profiles")
        if profiles is not None:
            if not isinstance(profiles, dict):
                raise InvalidTargetConfiguration("case metadata.mock_profiles must be an object")
            selected = profiles.get(self._config.profile) if self._config.profile else None
            if selected is not None:
                if not isinstance(selected, dict):
                    raise InvalidTargetConfiguration("selected case mock profile must be an object")
                config.update(selected)
        override = case.metadata.get("mock")
        if override is not None:
            if not isinstance(override, dict):
                raise InvalidTargetConfiguration("case metadata.mock must be an object")
            config.update(override)
        try:
            return MockTargetConfig.model_validate(config)
        except ValidationError as error:
            raise InvalidTargetConfiguration("invalid case mock configuration") from error


def _raise_if_cancelled(context: ExecutionContext) -> None:
    if context.cancellation.is_set():
        raise TargetCancelledError
