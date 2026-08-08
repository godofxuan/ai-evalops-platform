from app.domain.evaluation import EvaluationCase, TargetResult
from app.evaluators.retrieval_citation import RetrievalCitationEvaluator


def test_retrieval_and_citation_metrics_use_explicit_relevance_labels() -> None:
    result = RetrievalCitationEvaluator().evaluate(
        EvaluationCase(
            case_id="case-1",
            question="q",
            expected_answer="a",
            metadata={"relevant_source_ids": ["source-a", "source-b"]},
        ),
        TargetResult(
            answer="a",
            citations=({"source_id": "source-a"}, {"source_id": "irrelevant"}),
            sources=({"id": "source-a"}, {"id": "source-b"}, {"id": "irrelevant"}),
            trace={},
            token_usage=None,
            latency_ms=1,
        ),
        attempt_number=1,
    )

    assert result.metrics == {
        "retrieval_recall": 1.0,
        "citation_precision": 0.5,
        "citation_recall": 0.5,
        "citation_f1": 0.5,
    }


def test_retrieval_metrics_are_none_without_ground_truth_labels() -> None:
    result = RetrievalCitationEvaluator().evaluate(
        EvaluationCase(case_id="case-2", question="q", expected_answer="a", metadata={}),
        TargetResult(
            answer="a",
            citations=({"source_id": "source-a"},),
            sources=({"id": "source-a"},),
            trace={},
            token_usage=None,
            latency_ms=1,
        ),
        attempt_number=1,
    )

    assert result.metrics == {
        "retrieval_recall": None,
        "citation_precision": None,
        "citation_recall": None,
        "citation_f1": None,
    }
