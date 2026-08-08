from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.domain.evaluation import EvaluationCase, EvaluationResult, TargetResult


class Evaluator(Protocol):
    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        """Evaluate one successful target response."""


class UnsupportedEvaluatorError(ValueError):
    """The Run references an evaluator that this worker does not support."""


class EvaluatorCategory(StrEnum):
    DETERMINISTIC = "deterministic"
    OPERATIONAL = "operational"


@dataclass(frozen=True, slots=True)
class EvaluatorDescriptor:
    kind: str
    implementation_version: str
    category: EvaluatorCategory
    llm_judge: bool


@dataclass(frozen=True, slots=True)
class _EvaluatorRegistration:
    descriptor: EvaluatorDescriptor
    factory: Callable[[], Evaluator]


def _registry() -> dict[str, _EvaluatorRegistration]:
    from app.evaluators.basic_answer import BasicAnswerEvaluator
    from app.evaluators.execution import ExecutionEvaluator
    from app.evaluators.retrieval_citation import RetrievalCitationEvaluator

    registrations = (
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="basic_answer",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=BasicAnswerEvaluator,
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="execution",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.OPERATIONAL,
                llm_judge=False,
            ),
            factory=ExecutionEvaluator,
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="retrieval_citation",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=RetrievalCitationEvaluator,
        ),
    )
    return {registration.descriptor.kind: registration for registration in registrations}


def registered_evaluators() -> tuple[EvaluatorDescriptor, ...]:
    return tuple(registration.descriptor for registration in _registry().values())


def build_evaluator(kind: str, config: Mapping[str, Any]) -> Evaluator:
    del config
    try:
        registration = _registry()[kind]
    except KeyError:
        raise UnsupportedEvaluatorError(f"unsupported evaluator type: {kind}") from None
    return registration.factory()
