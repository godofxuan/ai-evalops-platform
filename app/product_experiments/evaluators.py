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


class ResultView(Protocol):
    @property
    def answer(self) -> str: ...

    @property
    def citations(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def tool_error(self) -> bool: ...


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
        return float(result.tool_error)


_REGISTRY: Mapping[str, CaseEvaluator] = {
    "reference_answer": ReferenceAnswerEvaluator(),
    "citation_correctness": CitationCorrectnessEvaluator(),
    "tool_error_rate": ToolErrorRateEvaluator(),
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


__all__ = ["CaseEvaluator", "registered_evaluators"]
