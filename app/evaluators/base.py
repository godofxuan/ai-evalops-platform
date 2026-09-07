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
    factory: Callable[[Mapping[str, Any]], Evaluator]


def _registry() -> dict[str, _EvaluatorRegistration]:
    from app.evaluators.basic_answer import BasicAnswerEvaluator
    from app.evaluators.execution import ExecutionEvaluator
    from app.evaluators.product import ProductAgentEvaluator, ProductQAEvaluator
    from app.evaluators.retrieval_citation import RetrievalCitationEvaluator

    registrations = (
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="product_agent_v2",
                implementation_version="product-v2",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=lambda config: ProductAgentEvaluator(
                max_observation_bytes_per_case=config.get("max_observation_bytes_per_case")
            ),
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="product_qa_v2",
                implementation_version="product-v2",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=lambda config: ProductQAEvaluator(
                max_observation_bytes_per_case=config.get("max_observation_bytes_per_case")
            ),
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="basic_answer",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=lambda _config: BasicAnswerEvaluator(),
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="execution",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.OPERATIONAL,
                llm_judge=False,
            ),
            factory=lambda _config: ExecutionEvaluator(),
        ),
        _EvaluatorRegistration(
            descriptor=EvaluatorDescriptor(
                kind="retrieval_citation",
                implementation_version="builtin-v1",
                category=EvaluatorCategory.DETERMINISTIC,
                llm_judge=False,
            ),
            factory=lambda _config: RetrievalCitationEvaluator(),
        ),
    )
    return {registration.descriptor.kind: registration for registration in registrations}


def registered_evaluators() -> tuple[EvaluatorDescriptor, ...]:
    return tuple(registration.descriptor for registration in _registry().values())


def build_evaluator(kind: str, config: Mapping[str, Any]) -> Evaluator:
    if kind in {"product_qa_v2", "product_agent_v2"}:
        if set(config) - {"max_attempts", "max_observation_bytes_per_case"}:
            raise UnsupportedEvaluatorError("product evaluator config contains unsupported fields")
        if "max_observation_bytes_per_case" in config:
            limit = config["max_observation_bytes_per_case"]
            if type(limit) is not int or not 1 <= limit <= 256 * 1024 * 1024:
                raise UnsupportedEvaluatorError("product observation budget config is invalid")
    try:
        registration = _registry()[kind]
    except KeyError:
        raise UnsupportedEvaluatorError(f"unsupported evaluator type: {kind}") from None
    return registration.factory(config)
