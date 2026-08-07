from collections import defaultdict
from typing import Any


class FaultEvidenceError(RuntimeError):
    """The fault matrix is incomplete or violates a correctness invariant."""


def reconcile_fault_run(
    bundle: dict[str, Any],
    *,
    expected_submitted: int,
    stale_result_attempted_count: int,
    stale_result_accepted_count: int,
    stale_failure_attempted_count: int,
    stale_failure_accepted_count: int,
    expected_final_status: str = "succeeded",
) -> dict[str, Any]:
    run = bundle["run_snapshot"]
    jobs = bundle["jobs"]
    attempts = bundle["attempts"]
    case_results = bundle["case_results"]
    violations: list[str] = []

    job_ids = [str(job["id"]) for job in jobs]
    unique_job_count = len(set(job_ids))
    status_counts: dict[str, int] = defaultdict(int)
    for job in jobs:
        status_counts[str(job["status"])] += 1
    completed_count = sum(status_counts[status] for status in ("succeeded", "failed", "cancelled"))
    orphan_running_count = sum(
        status_counts[status] for status in ("queued", "running", "retry_wait", "cancelling")
    )
    lost_count = expected_submitted - completed_count

    attempt_sequences: dict[str, list[int]] = defaultdict(list)
    for attempt in attempts:
        attempt_sequences[str(attempt["job_id"])].append(int(attempt["attempt_number"]))
    retry_count = 0
    for job in jobs:
        job_id = str(job["id"])
        sequence = sorted(attempt_sequences[job_id])
        expected_sequence = list(range(1, int(job["attempt_count"]) + 1))
        if sequence != expected_sequence:
            violations.append(f"attempt_sequence:{job_id}")
        retry_count += max(0, len(sequence) - 1)

    result_job_ids = [str(result["job_id"]) for result in case_results]
    result_case_keys = [(str(result["run_id"]), str(result["case_id"])) for result in case_results]
    duplicate_job_results = len(result_job_ids) - len(set(result_job_ids))
    duplicate_case_results = len(result_case_keys) - len(set(result_case_keys))
    duplicate_result_count = max(duplicate_job_results, duplicate_case_results)

    if len(jobs) != expected_submitted:
        violations.append("submitted_count")
    if unique_job_count != expected_submitted:
        violations.append("unique_job_count")
    if completed_count != expected_submitted or lost_count != 0:
        violations.append("lost_or_nonterminal_job")
    if orphan_running_count != 0:
        violations.append("orphan_running_job")
    if duplicate_result_count != 0:
        violations.append("duplicate_case_result")
    if len(case_results) != status_counts["succeeded"]:
        violations.append("case_result_terminal_mismatch")
    if int(run["total_jobs"]) != expected_submitted:
        violations.append("run_total_jobs")
    if int(run["succeeded_jobs"]) != status_counts["succeeded"]:
        violations.append("run_succeeded_jobs")
    if int(run["failed_jobs"]) != status_counts["failed"]:
        violations.append("run_failed_jobs")
    if int(run["cancelled_jobs"]) != status_counts["cancelled"]:
        violations.append("run_cancelled_jobs")
    if str(run["status"]) != expected_final_status:
        violations.append("unexpected_final_run_status")
    if stale_result_accepted_count != 0:
        violations.append("stale_result_accepted")
    if stale_failure_accepted_count != 0:
        violations.append("stale_failure_accepted")

    return {
        "run_id": str(run["id"]),
        "submitted_count": len(jobs),
        "unique_job_count": unique_job_count,
        "completed_count": completed_count,
        "succeeded_count": status_counts["succeeded"],
        "failed_count": status_counts["failed"],
        "cancelled_count": status_counts["cancelled"],
        "lost_count": lost_count,
        "retry_count": retry_count,
        "duplicate_case_result_count": duplicate_result_count,
        "duplicate_terminal_commit_count": duplicate_result_count,
        "stale_result_attempted_count": stale_result_attempted_count,
        "stale_result_accepted_count": stale_result_accepted_count,
        "stale_failure_attempted_count": stale_failure_attempted_count,
        "stale_failure_accepted_count": stale_failure_accepted_count,
        "orphan_running_count": orphan_running_count,
        "final_run_status": str(run["status"]),
        "final_state_correct": not violations,
        "invariants_passed": not violations,
        "violations": violations,
    }


def validate_fault_matrix(records: list[dict[str, Any]], *, repetitions: int) -> None:
    if repetitions < 1:
        raise FaultEvidenceError("repetitions must be positive")
    expected = {
        (scenario_id, repetition)
        for scenario_id in "ABCDEFGHI"
        for repetition in range(1, repetitions + 1)
    }
    observed = {
        (str(record.get("scenario_id")), int(record.get("repetition", 0))) for record in records
    }
    if len(records) != len(observed):
        raise FaultEvidenceError("duplicate scenario/repetition records are present")
    if observed != expected:
        raise FaultEvidenceError("the A-I repetition matrix is incomplete")
    if any(record.get("invariants_passed") is not True for record in records):
        raise FaultEvidenceError("one or more scenario invariants failed")
    for record in records:
        scenario_id = str(record["scenario_id"])
        if int(record.get("stale_result_accepted_count", 0)) != 0:
            raise FaultEvidenceError("a stale result was accepted")
        if int(record.get("stale_failure_accepted_count", 0)) != 0:
            raise FaultEvidenceError("a stale failure was accepted")
        if scenario_id == "C" and int(record.get("stale_result_attempted_count", 0)) < 1:
            raise FaultEvidenceError("scenario C did not attempt a stale result")
        if scenario_id == "D" and int(record.get("stale_failure_attempted_count", 0)) < 1:
            raise FaultEvidenceError("scenario D did not attempt a stale failure")
