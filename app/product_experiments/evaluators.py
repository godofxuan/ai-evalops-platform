"""Safe code-registered evaluator plugins for product experiments."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class CaseView(Protocol):
    @property
    def case_id(self) -> str: ...

    @property
    def reference_answer(self) -> str: ...

    @property
    def expected_citation_ids(self) -> tuple[str, ...]: ...

    @property
    def expected_tool_calls(self) -> Sequence[object]: ...

    @property
    def allowed_tools(self) -> tuple[str, ...]: ...

    @property
    def max_tool_calls(self) -> int | None: ...


class ResultView(Protocol):
    @property
    def answer(self) -> str: ...

    @property
    def citations(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def tool_error(self) -> bool: ...

    @property
    def tool_calls(self) -> Sequence[object]: ...

    @property
    def terminal_state(self) -> str | None: ...

    @property
    def budget_exhausted(self) -> bool: ...


class CaseEvaluator(Protocol):
    @property
    def name(self) -> str: ...

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        """Return a normalized score for one case/result pair."""


@dataclass(frozen=True, slots=True)
class ReferenceAnswerEvaluator:
    name: str = "reference_answer"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        return float(_normalize(result.answer) == _normalize(case.reference_answer))


@dataclass(frozen=True, slots=True)
class CitationCorrectnessEvaluator:
    name: str = "citation_correctness"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        expected = set(case.expected_citation_ids)
        if not expected:
            return 1.0
        actual = {
            str(value)
            for citation in result.citations
            for key in ("source_id", "id")
            if (value := citation.get(key)) is not None
        }
        return len(expected & actual) / len(expected)


@dataclass(frozen=True, slots=True)
class ToolErrorRateEvaluator:
    name: str = "tool_error_rate"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        del case
        call_error = any(
            getattr(call, "status", None) == "error" for call in getattr(result, "tool_calls", ())
        )
        return float(result.tool_error or call_error)


@dataclass(frozen=True, slots=True)
class AgentTaskCompletionEvaluator:
    name: str = "agent_task_completion"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        observed = getattr(result, "source_terminal_state", None) or result.terminal_state
        if observed == "answer":
            observed = "completed"
        expected = getattr(case, "expected_terminal_state", "completed")
        return float(
            observed == expected and _normalize(result.answer) == _normalize(case.reference_answer)
        )


@dataclass(frozen=True, slots=True)
class ToolSelectionAccuracyEvaluator:
    name: str = "tool_selection_accuracy"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        expected = [getattr(call, "name", None) for call in case.expected_tool_calls]
        actual = [getattr(call, "name", None) for call in result.tool_calls]
        return float(actual == expected)


@dataclass(frozen=True, slots=True)
class ToolArgumentValidityEvaluator:
    name: str = "tool_argument_validity"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        expected = [
            (getattr(call, "name", None), getattr(call, "arguments", None))
            for call in case.expected_tool_calls
        ]
        actual = [
            (getattr(call, "name", None), getattr(call, "arguments", None))
            for call in result.tool_calls
        ]
        return float(_json_equal(actual, expected))


def _json_equal(left: object, right: object) -> bool:
    """JSON structural equality: booleans are not numbers; numeric 1 equals 1.0."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass(frozen=True, slots=True)
class PolicyViolationRateEvaluator:
    name: str = "policy_violation_rate"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        allowed = set(case.allowed_tools)
        return float(any(getattr(call, "name", None) not in allowed for call in result.tool_calls))


@dataclass(frozen=True, slots=True)
class ToolBudgetViolationRateEvaluator:
    name: str = "tool_budget_violation_rate"

    def evaluate(self, case: CaseView, result: ResultView) -> float:
        maximum = case.max_tool_calls
        over_limit = maximum is not None and len(result.tool_calls) > maximum
        # Exhaustion is an observed stop condition, not proof of exceeding the limit.
        return float(over_limit)


_REGISTRY: Mapping[str, CaseEvaluator] = {
    "reference_answer": ReferenceAnswerEvaluator(),
    "citation_correctness": CitationCorrectnessEvaluator(),
    "tool_error_rate": ToolErrorRateEvaluator(),
    "agent_task_completion": AgentTaskCompletionEvaluator(),
    "tool_selection_accuracy": ToolSelectionAccuracyEvaluator(),
    "tool_argument_validity": ToolArgumentValidityEvaluator(),
    "policy_violation_rate": PolicyViolationRateEvaluator(),
    "tool_budget_violation_rate": ToolBudgetViolationRateEvaluator(),
}


def registered_evaluators(names: Sequence[str] | Iterable[str]) -> tuple[CaseEvaluator, ...]:
    selected: list[CaseEvaluator] = []
    for name in names:
        try:
            selected.append(_REGISTRY[name])
        except KeyError:
            raise ValueError(f"unknown evaluator: {name}") from None
    return tuple(selected)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def citation_evidence_scores(
    case: CaseView, result: ResultView
) -> tuple[float | None, float | None]:
    """Unique source-ID recall/precision, not semantic support of answer claims."""
    expected = set(case.expected_citation_ids)
    if not expected:
        return None, None
    actual: set[str] = set()
    unresolved = 0
    for citation in result.citations:
        value = citation.get("source_id", citation.get("id"))
        if isinstance(value, str) and value:
            actual.add(value)
        else:
            unresolved += 1
    matched = len(expected & actual)
    denominator = len(actual) + unresolved
    return matched / len(expected), matched / denominator if denominator else 0.0


__all__ = ["CaseEvaluator", "registered_evaluators"]
