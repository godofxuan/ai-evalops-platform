import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    question: str
    expected_answer: Any
    metadata: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EvaluationCase":
        case_id = payload.get("case_id")
        question = payload.get("question")
        metadata = payload.get("metadata")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case payload has an invalid case_id")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("case payload has an invalid question")
        if not isinstance(metadata, dict):
            raise ValueError("case payload has invalid metadata")
        return cls(
            case_id=case_id,
            question=question,
            expected_answer=payload.get("expected_answer"),
            metadata=dict(metadata),
        )


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: UUID
    job_id: UUID
    attempt_id: UUID
    attempt_number: int
    worker_id: str
    cancellation: asyncio.Event


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts must be nonnegative")


@dataclass(frozen=True, slots=True)
class TargetResult:
    answer: str | None
    citations: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...]
    trace: dict[str, Any]
    token_usage: TokenUsage | None
    latency_ms: int

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be nonnegative")


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    metrics: dict[str, Any]
