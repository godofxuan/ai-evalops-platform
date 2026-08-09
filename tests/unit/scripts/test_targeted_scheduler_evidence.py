from collections.abc import Sequence

from scripts.fair_capacity_evidence import FAIR_CAPACITY_DISTRIBUTIONS
from scripts.targeted_scheduler_evidence import assess_targeted_repetitions

SOURCE_COMMIT = "a" * 40


def _row(*, distribution: str, workers: int, throughput: float) -> dict[str, object]:
    return {
        "arm_id": f"fair-q1000-{distribution}-w{workers}-b1",
        "source_commit": SOURCE_COMMIT,
        "queue_size": 1_000,
        "distribution": distribution,
        "worker_concurrency": workers,
        "claim_batch_size": 1,
        "jobs_per_second": throughput,
        "claim_latency_p50_ms": 1.0,
        "claim_latency_p95_ms": 2.0,
        "claim_latency_p99_ms": 3.0,
        "reservation_latency_p50_ms": 0.2,
        "reservation_latency_p95_ms": 0.4,
        "reservation_latency_p99_ms": 0.6,
        "job_claim_latency_p50_ms": 0.8,
        "job_claim_latency_p95_ms": 1.6,
        "job_claim_latency_p99_ms": 2.4,
        "tenant_turn_reserved": 100,
        "tenant_turn_without_job": 2,
        "reservation_miss_rate": 0.02,
        "contention_retries": workers - 1,
        "contention_retry_per_success": (workers - 1) / 100,
        "empty_while_eligible": 0,
        "postgres_lock_waiting_connections_peak": 0,
        "worker_process_cpu_percent": 80.0,
        "worker_process_rss_bytes_peak": 100_000_000,
        "submitted_count": 100,
        "unique_job_count": 100,
        "terminal_count": 100,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
    }


def _repetitions(*, worker_8_ratio: float = 1.05) -> Sequence[Sequence[dict[str, object]]]:
    repetitions = []
    for repetition in range(4):
        rows = []
        for distribution in FAIR_CAPACITY_DISTRIBUTIONS:
            for workers in (1, 2, 4, 8):
                throughput = float(workers * 10 + repetition)
                if workers == 8:
                    throughput = float((40 + repetition) * worker_8_ratio)
                rows.append(_row(distribution=distribution, workers=workers, throughput=throughput))
        repetitions.append(rows)
    return repetitions


def test_targeted_gate_verifies_four_complete_repetitions_and_all_metrics() -> None:
    assessment = assess_targeted_repetitions(
        _repetitions(),
        source_commit=SOURCE_COMMIT,
    )

    assert assessment["status"] == "VERIFIED"
    assert assessment["repetition_count"] == 4
    assert len(assessment["groups"]) == 16
    assert len(assessment["self_scaling"]) == 4
    assert {row["status"] for row in assessment["self_scaling"]} == {"VERIFIED"}
    assert all(row["throughput_8_to_4_ratio"] >= 0.95 for row in assessment["self_scaling"])
    assert assessment["metric_contract"] == [
        "jobs_per_second",
        "claim_latency_p50_ms",
        "claim_latency_p95_ms",
        "claim_latency_p99_ms",
        "reservation_latency_p50_ms",
        "reservation_latency_p95_ms",
        "reservation_latency_p99_ms",
        "job_claim_latency_p50_ms",
        "job_claim_latency_p95_ms",
        "job_claim_latency_p99_ms",
        "tenant_turn_reserved",
        "tenant_turn_without_job",
        "reservation_miss_rate",
        "contention_retries",
        "contention_retry_per_success",
        "empty_while_eligible",
        "postgres_lock_waiting_connections_peak",
        "worker_process_cpu_percent",
        "worker_process_rss_bytes_peak",
    ]


def test_targeted_gate_marks_a_four_to_eight_regression_as_negative_scaling() -> None:
    assessment = assess_targeted_repetitions(
        _repetitions(worker_8_ratio=0.90),
        source_commit=SOURCE_COMMIT,
    )

    assert assessment["status"] == "NEGATIVE_SCALING"
    assert assessment["failures"] == [
        f"negative_scaling:{distribution}" for distribution in FAIR_CAPACITY_DISTRIBUTIONS
    ]
    assert {row["status"] for row in assessment["self_scaling"]} == {"NEGATIVE_SCALING"}


def test_targeted_gate_fails_closed_for_missing_repetition_or_correctness_failure() -> None:
    incomplete = assess_targeted_repetitions(
        _repetitions()[:3],
        source_commit=SOURCE_COMMIT,
    )
    assert incomplete["status"] == "FAILED"
    assert "repetition_count_must_equal_4" in incomplete["failures"]

    repetitions = [list(rows) for rows in _repetitions()]
    repetitions[2][0]["lost_count"] = 1
    invalid = assess_targeted_repetitions(repetitions, source_commit=SOURCE_COMMIT)
    assert invalid["status"] == "FAILED"
    assert invalid["failures"] == ["rep3:fair-q1000-single_tenant-w1-b1:lost_count_nonzero"]
