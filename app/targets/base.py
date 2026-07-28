from collections.abc import Mapping
from typing import Any, Protocol

from app.domain.evaluation import EvaluationCase, ExecutionContext, TargetResult


class EvaluationTarget(Protocol):
    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        """Execute one case without holding a database transaction."""


class InvalidTargetConfiguration(ValueError):
    """Target configuration violates validation or security policy."""


class UnsupportedTargetError(InvalidTargetConfiguration):
    """The worker does not implement the referenced target type."""


class TargetExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class TargetCancelledError(TargetExecutionError):
    def __init__(self) -> None:
        super().__init__("target_cancelled", "target execution was cancelled", retryable=False)


class TargetTimeoutError(TargetExecutionError):
    def __init__(self) -> None:
        super().__init__("target_timeout", "target request timed out", retryable=True)


class TargetInvalidResponseError(TargetExecutionError):
    def __init__(self, code: str = "target_invalid_response") -> None:
        super().__init__(code, "target response did not match the contract", retryable=False)


class TargetHTTPError(TargetExecutionError):
    def __init__(self, status_code: int) -> None:
        retryable = status_code in {408, 429, 500, 502, 503, 504}
        super().__init__(
            f"target_http_{status_code}",
            f"target returned HTTP {status_code}",
            retryable=retryable,
            status_code=status_code,
        )


def build_target(kind: str, config: Mapping[str, Any]) -> EvaluationTarget:
    from app.targets.http_rag import HTTPRAGTarget
    from app.targets.mock import MockTarget

    if kind == "mock":
        return MockTarget(config)
    if kind == "http_rag":
        return HTTPRAGTarget(config)
    raise UnsupportedTargetError(f"unsupported target type: {kind}")
