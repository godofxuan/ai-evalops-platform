from app.domain.evaluation import EvaluationCase, TargetResult, TokenUsage
from app.evaluators.execution import ExecutionEvaluator


def test_execution_evaluator_records_operational_metrics() -> None:
    case = EvaluationCase(
        case_id="case-1",
        question="What is 2 + 2?",
        expected_answer="4",
        metadata={},
    )
    target_result = TargetResult(
        answer="4",
        citations=(),
        sources=(),
        trace={},
        token_usage=TokenUsage(input_tokens=10, output_tokens=2),
        latency_ms=125,
    )

    result = ExecutionEvaluator().evaluate(case, target_result, attempt_number=3)

    assert result.metrics == {
        "execution_success": True,
        "latency_ms": 125,
        "input_tokens": 10,
        "output_tokens": 2,
        "attempt_count": 3,
        "succeeded_after_retry": True,
    }
