from copy import deepcopy
from pathlib import Path

import pytest

from scripts.export_fault_evidence import (
    EvidenceAdmissionError,
    normalize_verified_fault_evidence,
    write_csv,
)


def _report() -> tuple[dict[str, object], dict[str, object]]:
    results: list[dict[str, object]] = []
    for repetition in (1, 2, 3):
        for scenario_id in "ABCDEFGHI":
            submitted = 20 if scenario_id == "H" else 1
            results.append(
                {
                    "scenario_id": scenario_id,
                    "scenario": f"scenario-{scenario_id}",
                    "repetition": repetition,
                    "recovery_seconds": float(repetition),
                    "submitted_count": submitted,
                    "unique_job_count": submitted,
                    "completed_count": submitted,
                    "succeeded_count": submitted,
                    "failed_count": 0,
                    "lost_count": 0,
                    "retry_count": 20 if scenario_id == "H" else 0,
                    "duplicate_case_result_count": 0,
                    "duplicate_terminal_commit_count": 0,
                    "stale_result_attempted_count": 1 if scenario_id == "C" else 0,
                    "stale_result_accepted_count": 0,
                    "stale_failure_attempted_count": 1 if scenario_id == "D" else 0,
                    "stale_failure_accepted_count": 0,
                    "orphan_running_count": 0,
                    "invariants_passed": True,
                    "worker_container_changed": False,
                    "worker_restart_required": False,
                    "http_request_count": 20 if scenario_id == "I" else 0,
                    "http_success_count": 20 if scenario_id == "I" else 0,
                    "http_error_count": 0,
                    "unique_run_count": 1 if scenario_id == "I" else 0,
                }
            )
    report: dict[str, object] = {
        "status": "verified",
        "started_at": "2026-08-08T00:00:00Z",
        "configuration": {"source_commit": "a" * 40, "repetitions": 3},
        "results": results,
    }
    manifest: dict[str, object] = {
        "status": "complete",
        "run_id": "fault-test",
        "source_commit": "a" * 40,
        "repetitions": 3,
        "scenario_count": 27,
    }
    return manifest, report


def test_normalizer_exports_every_repetition_and_scenario_summary() -> None:
    manifest, report = _report()

    normalized = normalize_verified_fault_evidence(manifest, report, phase="after")

    assert len(normalized.result_rows) == 27
    assert len(normalized.summary_rows) == 9
    assert normalized.result_rows[0]["evidence_status"] == "VERIFIED"
    assert normalized.result_rows[0]["phase"] == "after"
    assert normalized.result_rows[0]["raw_evidence_path"] == (
        "docs/results/fault/fault-test/report.json"
    )
    scenario_h = next(row for row in normalized.summary_rows if row["scenario_id"] == "H")
    assert scenario_h["repetitions"] == 3
    assert scenario_h["successful_recoveries"] == 3
    assert scenario_h["recovery_seconds_median"] == 2.0
    assert scenario_h["submitted_count"] == 60
    assert scenario_h["retry_count"] == 60
    assert scenario_h["correctness_violations"] == 0
    scenario_i = next(row for row in normalized.summary_rows if row["scenario_id"] == "I")
    assert scenario_i["http_request_count"] == 60
    assert scenario_i["http_success_count"] == 60
    assert scenario_i["http_error_count"] == 0
    assert scenario_i["unique_run_count"] == 3
    assert scenario_i["worker_restarts_required"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "unverified_report",
        "source_mismatch",
        "failed_invariant",
        "lost_job",
        "accepted_stale_result",
    ],
)
def test_normalizer_fails_closed_for_unverified_or_incorrect_evidence(mutation: str) -> None:
    manifest, report = deepcopy(_report())
    results = report["results"]
    assert isinstance(results, list)
    first = results[0]
    assert isinstance(first, dict)
    if mutation == "unverified_report":
        report["status"] = "failed"
    elif mutation == "source_mismatch":
        manifest["source_commit"] = "b" * 40
    elif mutation == "failed_invariant":
        first["invariants_passed"] = False
    elif mutation == "lost_job":
        first["lost_count"] = 1
    elif mutation == "accepted_stale_result":
        first["stale_result_accepted_count"] = 1

    with pytest.raises(EvidenceAdmissionError):
        normalize_verified_fault_evidence(manifest, report, phase="after")


def test_csv_export_uses_lf_for_git_stable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "fault.csv"

    write_csv(output, ({"status": "VERIFIED", "count": 1},))

    assert output.read_bytes() == b"status,count\nVERIFIED,1\n"
