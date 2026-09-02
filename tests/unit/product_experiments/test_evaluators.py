from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.product_experiments.evaluators import registered_evaluators


def test_registered_evaluators_score_the_same_case_envelope() -> None:
    case = SimpleNamespace(
        case_id="case-1",
        reference_answer="A supported answer",
        expected_citation_ids=("source-1", "source-2"),
    )
    result = SimpleNamespace(
        answer="  a SUPPORTED answer ",
        citations=[{"source_id": "source-1"}],
        tool_error=False,
    )

    scores = {
        evaluator.name: evaluator.evaluate(case, result)
        for evaluator in registered_evaluators(
            ("reference_answer", "citation_correctness", "tool_error_rate")
        )
    }

    assert scores == {
        "reference_answer": 1.0,
        "citation_correctness": 0.5,
        "tool_error_rate": 0.0,
    }


def test_unknown_evaluator_cannot_execute_unregistered_tenant_code() -> None:
    with pytest.raises(ValueError, match="unknown evaluator"):
        registered_evaluators(("uploaded_python",))
