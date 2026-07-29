from app.domain.enums import JobStatus
from app.results.metrics import CaseOutcome, aggregate_metrics


def test_aggregate_metrics_uses_all_jobs_for_rates_and_successes_for_latency() -> None:
    summary = aggregate_metrics(
        [
            CaseOutcome(JobStatus.SUCCEEDED, 10, {"score": 0.0, "flag": True}),
            CaseOutcome(JobStatus.SUCCEEDED, 20, {"score": 0.5}),
            CaseOutcome(JobStatus.SUCCEEDED, 30, {"score": 1.0}),
            CaseOutcome(JobStatus.SUCCEEDED, 40, {"flag": False}),
            CaseOutcome(JobStatus.FAILED, None, {}),
        ]
    )

    assert summary.total_jobs == 5
    assert summary.completion_rate == 1.0
    assert summary.success_rate == 0.8
    assert summary.failure_rate == 0.2
    assert summary.latency.mean == 25.0
    assert summary.latency.p50 == 25.0
    assert summary.latency.p95 == 38.5
    assert summary.evaluator_metrics["score"].count == 3
    assert summary.evaluator_metrics["score"].mean == 0.5
    assert summary.evaluator_metrics["score"].p95 == 0.95
    assert "flag" not in summary.evaluator_metrics
