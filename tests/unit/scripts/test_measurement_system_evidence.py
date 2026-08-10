import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts.measurement_system_evidence import (
    MEASUREMENT_ORDER,
    assess_measurement_system,
    verify_sealed_manifest,
)

SOURCE = "a" * 40
MEASUREMENT_CODE = "b" * 40
WORKFLOW_RUN_ID = "123456789"
ARM = "fair-q1000-skew_20_to_1-w8-b1"


def _row(position: int, block: str, mode: str, mode_repetition: int) -> dict[str, object]:
    telemetry_on = mode == "ON"
    return {
        "run_id": f"measurement-{position}",
        "workflow_run_id": WORKFLOW_RUN_ID,
        "source_commit": SOURCE,
        "measurement_code_sha": MEASUREMENT_CODE,
        "arm_id": ARM,
        "queue_size": 1000,
        "distribution": "skew_20_to_1",
        "worker_concurrency": 8,
        "claim_batch_size": 1,
        "sample_jobs": 100,
        "measurement_mode": mode,
        "measurement_block": block,
        "measurement_order_position": position,
        "measurement_mode_repetition": mode_repetition,
        "jobs_per_second": 100.0,
        "claim_latency_p50_ms": 4.0,
        "claim_latency_p95_ms": 10.0,
        "claim_latency_p99_ms": 12.0,
        "worker_process_cpu_percent": 80.0,
        "worker_process_rss_bytes_peak": 100_000_000,
        "contention_retries": 2,
        "contention_retry_per_success": 0.02,
        "waiting_fallbacks": 1,
        "postgres_lock_waiting_connections_peak": 1,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "empty_while_eligible": 0,
        "telemetry_successful_sample_count": 10 if telemetry_on else 0,
        "telemetry_sampling_hz": 5,
        "telemetry_observed_wait_sample_count": 3 if telemetry_on else 0,
        "telemetry_observed_waiting_backends": 2 if telemetry_on else 0,
        "telemetry_error_count": 0,
        "telemetry_dropped_sample_count": 0,
        "telemetry_buffer_overflow_count": 0,
    }


def _valid_rows() -> list[dict[str, object]]:
    return [
        _row(position, block, mode, mode_repetition)
        for position, block, mode, mode_repetition in MEASUREMENT_ORDER
    ]


def _assess(
    rows: list[dict[str, object]],
    *,
    manifest_failures: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    return assess_measurement_system(
        rows,
        expected_source_commit=SOURCE,
        expected_measurement_code_sha=MEASUREMENT_CODE,
        expected_workflow_run_id=WORKFLOW_RUN_ID,
        manifest_failures=manifest_failures or {},
    )


def _assert_invalid(rows: list[dict[str, object]], failure: str) -> None:
    result = _assess(rows)
    assert result["status"] == "MEASUREMENT_SYSTEM_INVALID"
    assert failure in result["failures"]


def test_measurement_assessor_accepts_exact_valid_contract() -> None:
    result = _assess(_valid_rows())

    assert result["status"] == "MEASUREMENT_SYSTEM_VALID"
    assert result["final_decision"] == "QUALIFIED_FOR_FUTURE_FORMAL_ATTRIBUTION"
    assert result["formal_attribution"] == "NOT_RUN"


def test_measurement_assessor_rejects_wrong_arm() -> None:
    rows = _valid_rows()
    rows[0]["arm_id"] = "fair-q1000-single_tenant-w8-b1"
    _assert_invalid(rows, "arm_identity_invalid")


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("queue_size", 999, "queue_size_drift"),
        ("distribution", "single_tenant", "distribution_drift"),
        ("worker_concurrency", 4, "worker_concurrency_drift"),
        ("claim_batch_size", 2, "claim_batch_size_drift"),
        ("sample_jobs", 99, "sample_jobs_drift"),
    ],
)
def test_measurement_assessor_rejects_workload_spoof(
    field: str, value: object, failure: str
) -> None:
    rows = _valid_rows()
    rows[0][field] = value
    _assert_invalid(rows, failure)


def test_measurement_assessor_rejects_queue_spoof() -> None:
    test_measurement_assessor_rejects_workload_spoof("queue_size", 999, "queue_size_drift")


def test_measurement_assessor_rejects_distribution_spoof() -> None:
    test_measurement_assessor_rejects_workload_spoof(
        "distribution", "single_tenant", "distribution_drift"
    )


def test_measurement_assessor_rejects_worker_spoof() -> None:
    test_measurement_assessor_rejects_workload_spoof(
        "worker_concurrency", 4, "worker_concurrency_drift"
    )


def test_measurement_assessor_rejects_batch_spoof() -> None:
    test_measurement_assessor_rejects_workload_spoof(
        "claim_batch_size", 2, "claim_batch_size_drift"
    )


def test_measurement_assessor_rejects_sample_jobs_drift() -> None:
    test_measurement_assessor_rejects_workload_spoof("sample_jobs", 99, "sample_jobs_drift")


def test_measurement_assessor_rejects_wrong_order() -> None:
    rows = _valid_rows()
    rows[0]["measurement_mode"] = "ON"
    _assert_invalid(rows, "measurement_order_invalid")


def test_measurement_assessor_rejects_missing_repetition() -> None:
    _assert_invalid(_valid_rows()[:-1], "repetition_count_invalid")


def test_measurement_assessor_rejects_extra_repetition() -> None:
    rows = _valid_rows()
    rows.append(copy.deepcopy(rows[-1]))
    _assert_invalid(rows, "repetition_count_invalid")


def test_measurement_assessor_rejects_duplicate_mode_rep() -> None:
    rows = _valid_rows()
    rows[2]["measurement_mode_repetition"] = 1
    _assert_invalid(rows, "mode_repetition_identity_invalid")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_measurement_assessor_rejects_non_finite(value: float) -> None:
    rows = _valid_rows()
    rows[0]["jobs_per_second"] = value
    _assert_invalid(rows, "numeric_domain_invalid")


def test_measurement_assessor_rejects_nan() -> None:
    test_measurement_assessor_rejects_non_finite(float("nan"))


def test_measurement_assessor_rejects_inf() -> None:
    test_measurement_assessor_rejects_non_finite(float("inf"))


def test_measurement_assessor_rejects_bool_numeric() -> None:
    rows = _valid_rows()
    rows[0]["jobs_per_second"] = True
    _assert_invalid(rows, "numeric_domain_invalid")


def test_measurement_assessor_rejects_correctness_failure() -> None:
    rows = _valid_rows()
    rows[0]["lost_count"] = 1
    _assert_invalid(rows, "correctness_invalid")


def test_measurement_assessor_rejects_false_empty() -> None:
    rows = _valid_rows()
    rows[0]["empty_while_eligible"] = 1
    _assert_invalid(rows, "correctness_invalid")


def test_measurement_assessor_rejects_telemetry_error() -> None:
    rows = _valid_rows()
    rows[1]["telemetry_error_count"] = 1
    _assert_invalid(rows, "telemetry_integrity_invalid")


def test_measurement_assessor_rejects_buffer_overflow() -> None:
    rows = _valid_rows()
    rows[1]["telemetry_buffer_overflow_count"] = 1
    _assert_invalid(rows, "telemetry_integrity_invalid")


def test_measurement_assessor_rejects_dropped_samples() -> None:
    rows = _valid_rows()
    rows[1]["telemetry_dropped_sample_count"] = 1
    _assert_invalid(rows, "telemetry_integrity_invalid")


def test_measurement_assessor_rejects_sampling_frequency_drift() -> None:
    rows = _valid_rows()
    rows[1]["telemetry_sampling_hz"] = 10
    _assert_invalid(rows, "sampling_frequency_drift")


def test_measurement_assessor_rejects_manifest_drift(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text("{}\n", encoding="utf-8")
    manifest = {
        "files": {
            "payload.json": {
                "size_bytes": payload.stat().st_size,
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            }
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    payload.write_text('{"drift":true}\n', encoding="utf-8")

    failures = verify_sealed_manifest(tmp_path)
    result = _assess(_valid_rows(), manifest_failures={"measurement-1": failures})

    assert failures
    assert result["status"] == "MEASUREMENT_SYSTEM_INVALID"
    assert "manifest_invalid" in result["failures"]


def test_measurement_assessor_reports_frozen_statistics_without_changing_gate() -> None:
    rows = _valid_rows()
    for index, row in enumerate(rows):
        row["jobs_per_second"] = 90.0 + index
        row["claim_latency_p95_ms"] = 100.0 + index

    result = _assess(rows)
    throughput = result["statistics"]["jobs_per_second"]

    assert set(throughput["OFF"]) == {
        "min",
        "max",
        "mean",
        "median",
        "range",
        "range_over_mean",
        "mad",
    }
    assert len(result["paired_block_observations"]) == 4
