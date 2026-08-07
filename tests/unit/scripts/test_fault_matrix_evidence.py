from copy import deepcopy

import pytest

from scripts.fault_matrix_evidence import (
    FaultEvidenceError,
    reconcile_fault_run,
    validate_fault_matrix,
)


def _bundle() -> dict[str, object]:
    return {
        "run_snapshot": {
            "id": "run-1",
            "status": "succeeded",
            "total_jobs": 1,
            "succeeded_jobs": 1,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
        },
        "jobs": [
            {
                "id": "job-1",
                "run_id": "run-1",
                "case_id": "case-1",
                "status": "succeeded",
                "attempt_count": 2,
            }
        ],
        "attempts": [
            {"job_id": "job-1", "attempt_number": 1, "outcome": "lease_expired"},
            {"job_id": "job-1", "attempt_number": 2, "outcome": "succeeded"},
        ],
        "case_results": [{"job_id": "job-1", "run_id": "run-1", "case_id": "case-1"}],
    }


def test_reconciliation_counts_retry_and_zero_loss_without_inventing_attempts() -> None:
    result = reconcile_fault_run(
        _bundle(),
        expected_submitted=1,
        stale_result_attempted_count=1,
        stale_result_accepted_count=0,
        stale_failure_attempted_count=0,
        stale_failure_accepted_count=0,
    )

    assert result["submitted_count"] == 1
    assert result["unique_job_count"] == 1
    assert result["completed_count"] == 1
    assert result["retry_count"] == 1
    assert result["lost_count"] == 0
    assert result["duplicate_case_result_count"] == 0
    assert result["stale_result_accepted_count"] == 0
    assert result["invariants_passed"] is True


@pytest.mark.parametrize(
    "mutation",
    ["lost", "duplicate_result", "attempt_gap", "accepted_stale_result"],
)
def test_reconciliation_fails_closed_on_correctness_violation(mutation: str) -> None:
    bundle = deepcopy(_bundle())
    stale_accepted = 0
    if mutation == "lost":
        bundle["jobs"][0]["status"] = "running"  # type: ignore[index]
        bundle["case_results"] = []
    elif mutation == "duplicate_result":
        bundle["case_results"].append(  # type: ignore[union-attr]
            {"job_id": "job-1", "run_id": "run-1", "case_id": "case-1"}
        )
    elif mutation == "attempt_gap":
        bundle["attempts"][1]["attempt_number"] = 3  # type: ignore[index]
    elif mutation == "accepted_stale_result":
        stale_accepted = 1

    result = reconcile_fault_run(
        bundle,
        expected_submitted=1,
        stale_result_attempted_count=1,
        stale_result_accepted_count=stale_accepted,
        stale_failure_attempted_count=0,
        stale_failure_accepted_count=0,
    )

    assert result["invariants_passed"] is False
    assert result["violations"]


def test_matrix_requires_all_scenarios_each_repetition_and_explicit_c_d_fencing() -> None:
    records = []
    for repetition in (1, 2, 3):
        for scenario_id in "ABCDEFGHI":
            record = {
                "scenario_id": scenario_id,
                "repetition": repetition,
                "invariants_passed": True,
                "stale_result_attempted_count": 1 if scenario_id == "C" else 0,
                "stale_result_accepted_count": 0,
                "stale_failure_attempted_count": 1 if scenario_id == "D" else 0,
                "stale_failure_accepted_count": 0,
            }
            records.append(record)

    validate_fault_matrix(records, repetitions=3)

    records[-1]["invariants_passed"] = False
    with pytest.raises(FaultEvidenceError):
        validate_fault_matrix(records, repetitions=3)
