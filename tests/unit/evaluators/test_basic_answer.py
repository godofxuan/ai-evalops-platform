from app.domain.evaluation import EvaluationCase, TargetResult, TokenUsage
from app.evaluators.basic_answer import BasicAnswerEvaluator


def test_basic_answer_evaluator_uses_explicit_lexical_metric_names() -> None:
    case = EvaluationCase(
        case_id="case-1",
        question="Capital of France?",
        expected_answer="Paris, France",
        metadata={"keywords": ["Paris", "France", "Europe"]},
    )
    target_result = TargetResult(
        answer="  PARIS,   France  ",
        citations=({"source_id": "wiki-france"},),
        sources=({"id": "wiki-france", "visible": True},),
        trace={},
        token_usage=TokenUsage(input_tokens=8, output_tokens=3),
        latency_ms=20,
    )

    result = BasicAnswerEvaluator().evaluate(case, target_result, attempt_number=1)

    assert result.metrics["lexical_exact_match"] is False
    assert result.metrics["lexical_normalized_exact_match"] is True
    assert result.metrics["lexical_keyword_coverage"] == 2 / 3
    assert result.metrics["has_answer"] is True
    assert result.metrics["has_citations"] is True
    assert "semantic_accuracy" not in result.metrics


def test_keyword_coverage_is_none_without_explicit_keyword_labels() -> None:
    result = BasicAnswerEvaluator().evaluate(
        EvaluationCase(
            case_id="case-2",
            question="q",
            expected_answer="expected",
            metadata={},
        ),
        TargetResult(
            answer="answer",
            citations=(),
            sources=(),
            trace={},
            token_usage=None,
            latency_ms=1,
        ),
        attempt_number=1,
    )

    assert result.metrics["lexical_keyword_coverage"] is None
