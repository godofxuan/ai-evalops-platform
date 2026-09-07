import hashlib
import json

import pytest

from app.domain.evaluation import EvaluationCase, TargetResult
from app.evaluators.base import UnsupportedEvaluatorError, build_evaluator
from app.product_experiments.dataset_mapping import map_product_dataset


def test_product_worker_does_not_silently_ignore_scoring_policy_overrides() -> None:
    with pytest.raises(UnsupportedEvaluatorError, match="config"):
        build_evaluator("product_qa_v2", {"citation_precision_min": 0.0})


def test_worker_product_agent_scores_correct_zero_tool_refusal_without_citations() -> None:
    payload = json.dumps(
        [
            {
                "case_id": str(index),
                "category": "safety",
                "prompt": "unsafe request",
                "reference_answer": "denied",
                "allowed_tools": [],
                "max_tool_calls": 0,
                "expected_terminal_state": "refusal",
            }
            for index in range(2)
        ]
    ).encode()
    mapped = map_product_dataset(payload, expected_sha256=hashlib.sha256(payload).hexdigest())
    case = EvaluationCase.from_payload(mapped.dataset.cases[0].model_dump())
    target = TargetResult(
        answer="denied",
        citations=(),
        sources=(),
        token_usage=None,
        latency_ms=5,
        trace={
            "cost_usd": 0.0,
            "tool_calls": [],
            "tool_error": False,
            "terminal_state": "blocked",
            "source_terminal_state": "refusal",
            "budget_exhausted": False,
        },
    )
    result = build_evaluator("product_agent_v2", {}).evaluate(case, target, attempt_number=2)
    assert result.metrics["product_status"] == "OBSERVED"
    assert result.metrics["product_scores"]["agent_task_completion"] == 1.0
    assert result.metrics["product_scores"]["tool_budget_violation_rate"] == 0.0
    assert "citation_correctness" not in result.metrics["product_scores"]


def test_worker_product_qa_uses_source_id_scores_and_preserves_observation() -> None:
    payload = json.dumps(
        [
            {
                "case_id": str(index),
                "category": "qa",
                "prompt": "question",
                "reference_answer": "answer",
                "expected_citation_ids": ["gold"],
            }
            for index in range(2)
        ]
    ).encode()
    mapped = map_product_dataset(payload, expected_sha256=hashlib.sha256(payload).hexdigest())
    case = EvaluationCase.from_payload(mapped.dataset.cases[0].model_dump())
    target = TargetResult(
        answer="answer",
        citations=({"source_id": "gold"}, {"source_id": "invented"}),
        sources=(),
        trace={"cost_usd": 0.0},
        token_usage=None,
        latency_ms=5,
    )
    result = build_evaluator("product_qa_v2", {}).evaluate(case, target, attempt_number=1)
    assert result.metrics["product_status"] == "OBSERVED"
    assert result.metrics["product_scores"]["reference_answer"] == 1.0
    assert result.metrics["product_scores"]["citation_recall"] == 1.0
    assert result.metrics["product_scores"]["citation_precision"] == 0.5
    assert result.metrics["product_observation"]["cost_usd"] == 0.0
