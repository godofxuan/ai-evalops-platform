from collections.abc import Mapping
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


def build_evaluator(kind: str, config: Mapping[str, Any]) -> Evaluator:
    from app.evaluators.basic_answer import BasicAnswerEvaluator
    from app.evaluators.execution import ExecutionEvaluator

    del config
    if kind == "execution":
        return ExecutionEvaluator()
    if kind == "basic_answer":
        return BasicAnswerEvaluator()
    raise UnsupportedEvaluatorError(f"unsupported evaluator type: {kind}")
