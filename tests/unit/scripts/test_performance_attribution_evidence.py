import pytest

from scripts.fair_capacity_evidence import (
    FAIR_CAPACITY_DISTRIBUTIONS,
    FAIR_CAPACITY_WORKER_COUNTS,
)
from scripts.performance_attribution_evidence import (
    assess_instrumentation_overhead,
    assess_performance_attribution,
)

SOURCE = "a" * 40
STAGES = (
    "scheduler_coordination_wait_ms",
    "tenant_permit_wait_ms",
    "job_row_wait_ms",
    "durable_sequence_wait_ms",
    "transaction_commit_ms",
    "claim_total_ms",
)


def _row(
    *,
    distribution: str,
    workers: int,
    instrumentation: bool,
    throughput: float = 100.0,
    claim_p95: float = 10.0,
) -> dict[str, object]:
    failing = distribution != "many_small_tenants"
    high_workers = workers == 8
    stage_wait = 4.0 if failing and high_workers else 1.0
    permit_wait = 3.0 if failing and high_workers else 1.0 if failing else 0.5
    row: dict[str, object] = {
        "arm_id": f"fair-q1000-{distribution}-w{workers}-b1",
        "source_commit": SOURCE,
        "performance_attribution_enabled": instrumentation,
        "submitted_count": 100,
        "jobs_per_second": throughput,
        "claim_latency_p50_ms": 20.0 if high_workers else 10.0,
        "claim_latency_p95_ms": claim_p95,
        "contention_retries": 10 if failing and high_workers else 1,
        "waiting_fallbacks": 10 if failing and high_workers else 1,
        "worker_process_cpu_percent": 80.0,
        "worker_process_rss_bytes_peak": 100_000_000,
        "job_skip_locked_miss_count": 4 if failing and high_workers else 1 if failing else 0,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "empty_while_eligible": 0,
    }
    for stage in STAGES:
        value = permit_wait if stage == "tenant_permit_wait_ms" else stage_wait
        if distribution == "many_small_tenants" and high_workers:
            value = 0.6 if stage == "tenant_permit_wait_ms" else 1.1
        row[f"{stage}_count"] = 100
        row[f"{stage}_sum"] = value * 100
        row[f"{stage}_p50"] = value
        row[f"{stage}_p95"] = value
        row[f"{stage}_p99"] = value
    return row


def _repetition(
    *,
    instrumentation: bool,
    overhead_throughput: float = 100.0,
    overhead_claim_p95: float = 10.0,
) -> list[dict[str, object]]:
    return [
        _row(
            distribution=distribution,
            workers=workers,
            instrumentation=instrumentation,
            throughput=(
                overhead_throughput if distribution == "skew_20_to_1" and workers == 8 else 100.0
            ),
            claim_p95=(
                overhead_claim_p95 if distribution == "skew_20_to_1" and workers == 8 else 10.0
            ),
        )
        for distribution in FAIR_CAPACITY_DISTRIBUTIONS
        for workers in FAIR_CAPACITY_WORKER_COUNTS
    ]


def test_attribution_assessor_applies_overhead_gate_and_preregistered_hypotheses() -> None:
    assessment = assess_performance_attribution(
        off_repetitions=[_repetition(instrumentation=False) for _ in range(3)],
        on_repetitions=[
            _repetition(
                instrumentation=True,
                overhead_throughput=98.0,
                overhead_claim_p95=10.5,
            )
            for _ in range(3)
        ],
        formal_repetitions=[_repetition(instrumentation=True) for _ in range(4)],
        source_commit=SOURCE,
    )

    assert assessment["status"] == "ATTRIBUTION_COMPLETE"
    assert assessment["overhead"]["status"] == "VALID"
    assert assessment["overhead"]["throughput_relative_change"] == pytest.approx(-0.02)
    assert assessment["overhead"]["claim_p95_relative_change"] == pytest.approx(0.05)
    assert assessment["hypotheses"]["H1_scheduler_coordination_singleton"]["status"] == (
        "SUPPORTED"
    )
    assert assessment["hypotheses"]["H2_tenant_permit_contention"]["status"] == "SUPPORTED"
    assert assessment["hypotheses"]["H3_skip_locked_retry_feedback"]["status"] == "SUPPORTED"


def test_attribution_assessor_stops_when_instrumentation_is_too_intrusive() -> None:
    assessment = assess_performance_attribution(
        off_repetitions=[_repetition(instrumentation=False) for _ in range(3)],
        on_repetitions=[
            _repetition(instrumentation=True, overhead_throughput=80.0) for _ in range(3)
        ],
        formal_repetitions=[_repetition(instrumentation=True) for _ in range(4)],
        source_commit=SOURCE,
    )

    assert assessment["status"] == "INSTRUMENTATION_TOO_INTRUSIVE"
    assert assessment["overhead"]["status"] == "INSTRUMENTATION_TOO_INTRUSIVE"
    assert assessment["groups"] == []
    assert assessment["hypotheses"] == {}


def test_overhead_only_assessor_can_gate_formal_execution() -> None:
    assessment = assess_instrumentation_overhead(
        off_repetitions=[_repetition(instrumentation=False) for _ in range(3)],
        on_repetitions=[
            _repetition(instrumentation=True, overhead_throughput=98.0) for _ in range(3)
        ],
        source_commit=SOURCE,
    )

    assert assessment["status"] == "VALID"
    assert assessment["failures"] == []


def test_attribution_assessor_rejects_nonfinite_or_source_drift() -> None:
    formal = [_repetition(instrumentation=True) for _ in range(4)]
    formal[0][0]["scheduler_coordination_wait_ms_sum"] = float("nan")
    formal[1][0]["source_commit"] = "b" * 40

    assessment = assess_performance_attribution(
        off_repetitions=[_repetition(instrumentation=False) for _ in range(3)],
        on_repetitions=[_repetition(instrumentation=True) for _ in range(3)],
        formal_repetitions=formal,
        source_commit=SOURCE,
    )

    assert assessment["status"] == "FAILED"
    assert any(
        "scheduler_coordination_wait_ms_invalid" in value for value in assessment["failures"]
    )
    assert any("source_commit_mismatch" in value for value in assessment["failures"])
