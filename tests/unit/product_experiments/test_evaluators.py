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


def test_agent_evaluators_expose_selection_arguments_policy_budget_and_completion() -> None:
    case = SimpleNamespace(
        case_id="agent-1",
        reference_answer="done",
        expected_citation_ids=(),
        expected_tool_calls=(SimpleNamespace(name="search", arguments={"q": "safe"}),),
        allowed_tools=("search",),
        max_tool_calls=1,
    )
    result = SimpleNamespace(
        answer="done",
        citations=[],
        tool_error=False,
        tool_calls=(
            SimpleNamespace(name="admin_delete", arguments={"q": "wrong"}, status="success"),
            SimpleNamespace(name="search", arguments={"q": "safe"}, status="success"),
        ),
        terminal_state="completed",
        budget_exhausted=False,
    )

    names = (
        "agent_task_completion",
        "tool_selection_accuracy",
        "tool_argument_validity",
        "policy_violation_rate",
        "tool_budget_violation_rate",
        "tool_error_rate",
    )
    scores = {item.name: item.evaluate(case, result) for item in registered_evaluators(names)}

    assert scores == {
        "agent_task_completion": 1.0,
        "tool_selection_accuracy": 0.0,
        "tool_argument_validity": 0.0,
        "policy_violation_rate": 1.0,
        "tool_budget_violation_rate": 1.0,
        "tool_error_rate": 0.0,
    }
