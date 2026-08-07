from copy import deepcopy
from pathlib import Path

import pytest

from scripts.export_load_evidence import (
    EvidenceAdmissionError,
    normalize_verified_load_evidence,
    write_csv,
)


def _inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    arms = [
        {
            "arm_id": f"io-r{repetition}-w{workers}",
            "workload": "io_latency_v1",
            "workers": workers,
            "repetition": repetition,
        }
        for workers in (1, 2)
        for repetition in (1, 2, 3)
    ]
    summaries: dict[str, dict[str, object]] = {}
    reconciliations: dict[str, dict[str, object]] = {}
    throughput = {
        (1, 1): 10.0,
        (1, 2): 11.0,
        (1, 3): 12.0,
        (2, 1): 18.0,
        (2, 2): 20.0,
        (2, 3): 22.0,
    }
    for arm in arms:
        arm_id = str(arm["arm_id"])
        workers_value = arm["workers"]
        repetition_value = arm["repetition"]
        assert isinstance(workers_value, int)
        assert isinstance(repetition_value, int)
        workers = workers_value
        repetition = repetition_value
        summaries[arm_id] = {
            "arm": arm,
            "summary": {
                "valid_for_capacity_comparison": True,
                "throughput_cases_per_second": throughput[(workers, repetition)],
                "end_to_end_ms": 1_000.0 / workers,
                "case_latency_ms": {"p50": 25.0, "p95": 25.0, "p99": 25.0},
                "queue_wait_ms": {"p50": 100.0, "p95": 200.0, "p99": 250.0},
                "retry_queue_wait_ms": {
                    "count": 0,
                    "p50": None,
                    "p95": None,
                    "p99": None,
                },
                "claim_latency_ms": {"mean_ms": 3.0},
                "db_transaction_latency_ms": {
                    "result": {"mean_ms": 4.0},
                },
                "db_lock_wait": {"peak_waiting_connections": 0},
                "postgres_connections": {"peak": 10 + workers},
                "retry_count": 0,
                "collector_missed_samples": 0,
                "stale_submission_rejection": {
                    "evidence": "NOT_RUN",
                    "observed": 0,
                },
                "worker_cluster_resources": {
                    "status": "VERIFIED",
                    "cpu_percent": {"peak": 40.0 * workers},
                    "rss_bytes": {"peak": 100_000_000 * workers},
                },
            },
        }
        reconciliations[arm_id] = {
            "valid_for_capacity_comparison": True,
            "duplicate_result_job_ids": [],
            "duplicate_result_run_case_keys": [],
            "status_counts": {
                "queued": 0,
                "running": 0,
                "retry_wait": 0,
                "succeeded": 500,
                "failed": 0,
                "cancelling": 0,
                "cancelled": 0,
            },
            "retry_count": 0,
            "attempt_sequences": {str(index): [1] for index in range(500)},
            "binding_mismatches": [],
            "violations": [],
        }
    manifest: dict[str, object] = {
        "run_id": "gate1-test",
        "provenance": {"source_commit": "a" * 40},
        "configuration": {"values": {"cases": 500, "warmup_cases": 50, "repetitions": 3}},
    }
    aggregate: dict[str, object] = {
        "gate_evaluation": {
            "quality_gate": {
                "status": "VERIFIED",
                "expected_arm_count": len(arms),
                "observed_arm_count": len(arms),
                "expected_arms_complete": True,
                "missing_arm_ids": [],
                "invalid_arm_ids": [],
            }
        }
    }
    return manifest, aggregate, arms, summaries, reconciliations


def test_normalizer_uses_all_repetitions_and_does_not_invent_stale_write_zero() -> None:
    normalized = normalize_verified_load_evidence(*_inputs())

    assert len(normalized.arm_rows) == 6
    assert all(row["stale_submission_evidence"] == "NOT_RUN" for row in normalized.arm_rows)
    assert all(row["stale_submission_accepted_count"] == "" for row in normalized.arm_rows)
    assert all(row["lost_count"] == 0 for row in normalized.arm_rows)
    assert all(row["queue_wait_p95_ms"] == 200.0 for row in normalized.arm_rows)
    assert all(row["retry_queue_wait_p95_ms"] == "" for row in normalized.arm_rows)
    assert all(row["postgres_connections_peak"] in {11, 12} for row in normalized.arm_rows)

    one_worker, two_workers = normalized.scaling_rows
    assert one_worker["throughput_median_cases_per_second"] == 11.0
    assert two_workers["throughput_median_cases_per_second"] == 20.0
    assert two_workers["speedup_vs_one_worker"] == pytest.approx(20.0 / 11.0)
    assert two_workers["parallel_efficiency"] == pytest.approx(10.0 / 11.0)


def test_csv_export_is_stable_through_repository_lf_normalization(tmp_path: Path) -> None:
    output = tmp_path / "evidence.csv"

    write_csv(output, ({"status": "VERIFIED", "count": 1},))

    assert b"\r\n" not in output.read_bytes()
    assert output.read_bytes() == b"status,count\nVERIFIED,1\n"


@pytest.mark.parametrize(
    "mutation",
    [
        "quality_gate_failed",
        "invalid_arm",
        "duplicate_result",
        "orphan_running",
        "collector_gap",
    ],
)
def test_normalizer_fails_closed_when_required_evidence_is_not_verified(
    mutation: str,
) -> None:
    manifest, aggregate, arms, summaries, reconciliations = deepcopy(_inputs())
    first_id = str(arms[0]["arm_id"])
    if mutation == "quality_gate_failed":
        aggregate["gate_evaluation"]["quality_gate"]["status"] = "FAILED"  # type: ignore[index]
    elif mutation == "invalid_arm":
        reconciliations[first_id]["valid_for_capacity_comparison"] = False
    elif mutation == "duplicate_result":
        reconciliations[first_id]["duplicate_result_job_ids"] = ["job-1"]
    elif mutation == "orphan_running":
        reconciliations[first_id]["status_counts"]["succeeded"] = 499  # type: ignore[index]
        reconciliations[first_id]["status_counts"]["running"] = 1  # type: ignore[index]
    elif mutation == "collector_gap":
        summaries[first_id]["summary"]["collector_missed_samples"] = 1  # type: ignore[index]

    with pytest.raises(EvidenceAdmissionError):
        normalize_verified_load_evidence(
            manifest,
            aggregate,
            arms,
            summaries,
            reconciliations,
        )
