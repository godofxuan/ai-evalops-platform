import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from statistics import median
from typing import Any

from scripts.experiment_support import ExperimentError, percentile

GATE1_RESULT_SCHEMA_VERSION = 3
GATE1_GATE_POLICY_VERSION = 1
GATE1_QUALITY_GATE_POLICY = "all_expected_arms_valid_for_capacity_comparison"

JOB_STATUSES = (
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "cancelling",
    "cancelled",
)
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def _derive_run_status(status_counts: dict[str, int]) -> str:
    present = {status for status, count in status_counts.items() if count}
    if present == {"succeeded"}:
        return "succeeded"
    if present == {"failed"}:
        return "failed"
    if present <= TERMINAL_JOB_STATUSES:
        return "partially_succeeded"
    if present == {"queued"}:
        return "queued"
    return "running"


def reconcile_arm(
    *,
    expected_jobs: int,
    expected_binding: Mapping[str, str] | None = None,
    run_snapshot: dict[str, Any],
    jobs: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    case_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile one measured arm from durable PostgreSQL rows."""
    result_job_counts = Counter(str(result["job_id"]) for result in case_results)
    result_run_case_counts = Counter(
        (str(result["run_id"]), str(result["case_id"])) for result in case_results
    )
    duplicate_result_job_ids = sorted(
        job_id for job_id, count in result_job_counts.items() if count > 1
    )
    duplicate_result_run_case_keys = [
        {"run_id": run_id, "case_id": case_id}
        for (run_id, case_id), count in sorted(result_run_case_counts.items())
        if count > 1
    ]
    succeeded_job_ids = {str(job["id"]) for job in jobs if str(job["status"]) == "succeeded"}
    succeeded_jobs_without_exactly_one_result = sorted(
        job_id for job_id in succeeded_job_ids if result_job_counts[job_id] != 1
    )
    observed_status_counts = Counter(str(job["status"]) for job in jobs)
    status_counts = {status: observed_status_counts.get(status, 0) for status in JOB_STATUSES}
    run_counter_fields = {
        "total_jobs": len(jobs),
        "succeeded_jobs": status_counts["succeeded"],
        "failed_jobs": status_counts["failed"],
        "cancelled_jobs": status_counts["cancelled"],
    }
    reported_run_counters = {field: int(run_snapshot[field]) for field in run_counter_fields}
    nonterminal_job_ids = sorted(
        str(job["id"]) for job in jobs if str(job["status"]) not in TERMINAL_JOB_STATUSES
    )
    derived_run_status = _derive_run_status(status_counts)
    attempts_by_job: defaultdict[str, list[int]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_job[str(attempt["job_id"])].append(int(attempt["attempt_number"]))
    attempt_sequences = {str(job["id"]): sorted(attempts_by_job[str(job["id"])]) for job in jobs}
    attempt_sequence_mismatches = [
        {
            "job_id": str(job["id"]),
            "expected": list(range(1, int(job["attempt_count"]) + 1)),
            "observed": attempt_sequences[str(job["id"])],
        }
        for job in jobs
        if attempt_sequences[str(job["id"])] != list(range(1, int(job["attempt_count"]) + 1))
    ]
    retry_count = sum(max(int(job["attempt_count"]) - 1, 0) for job in jobs)
    binding_mismatches = {
        field: {
            "expected": expected,
            "observed": (None if run_snapshot.get(field) is None else str(run_snapshot[field])),
        }
        for field, expected in (expected_binding or {}).items()
        if str(run_snapshot.get(field)) != expected
    }

    violations: list[dict[str, Any]] = []
    if binding_mismatches:
        violations.append(
            {
                "code": "arm_binding_mismatch",
                "fields": binding_mismatches,
            }
        )
    if len(jobs) != expected_jobs:
        violations.append(
            {
                "code": "expected_job_count_mismatch",
                "expected": expected_jobs,
                "observed": len(jobs),
            }
        )
    if duplicate_result_job_ids:
        violations.append(
            {
                "code": "duplicate_case_results_by_job",
                "keys": duplicate_result_job_ids,
            }
        )
    if duplicate_result_run_case_keys:
        violations.append(
            {
                "code": "duplicate_case_results_by_run_case",
                "keys": duplicate_result_run_case_keys,
            }
        )
    if succeeded_jobs_without_exactly_one_result:
        violations.append(
            {
                "code": "succeeded_job_without_exactly_one_result",
                "job_ids": succeeded_jobs_without_exactly_one_result,
            }
        )
    if reported_run_counters != run_counter_fields:
        violations.append(
            {
                "code": "run_counters_do_not_match_job_states",
                "reported": reported_run_counters,
                "observed": run_counter_fields,
            }
        )
    if nonterminal_job_ids:
        violations.append(
            {
                "code": "unexplained_nonterminal_jobs",
                "job_ids": nonterminal_job_ids,
            }
        )
    if str(run_snapshot["status"]) != derived_run_status:
        violations.append(
            {
                "code": "final_run_status_inconsistent",
                "reported": str(run_snapshot["status"]),
                "derived": derived_run_status,
            }
        )
    if attempt_sequence_mismatches:
        violations.append(
            {
                "code": "attempt_sequence_mismatch",
                "jobs": attempt_sequence_mismatches,
            }
        )

    return {
        "valid_for_capacity_comparison": not violations,
        "duplicate_result_job_ids": duplicate_result_job_ids,
        "duplicate_result_run_case_keys": duplicate_result_run_case_keys,
        "status_counts": status_counts,
        "retry_count": retry_count,
        "attempt_sequences": attempt_sequences,
        "binding_mismatches": binding_mismatches,
        "violations": violations,
    }


def _verified_distribution(values: list[float]) -> dict[str, Any]:
    return {
        "evidence": "VERIFIED",
        "count": len(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def summarize_arm(
    *,
    reconciliation: dict[str, Any],
    measurement_seconds: float,
    end_to_end_ms: float,
    jobs: list[dict[str, Any]],
    case_results: list[dict[str, Any]],
    attempts: Sequence[dict[str, Any]] = (),
    collector_samples: Mapping[str, Sequence[float | int]] | None = None,
) -> dict[str, Any]:
    """Summarize only measurements supported by supplied raw evidence."""
    terminal_jobs = [job for job in jobs if str(job["status"]) in TERMINAL_JOB_STATUSES]
    successful_jobs = [job for job in jobs if str(job["status"]) == "succeeded"]
    case_latencies = [float(result["latency_ms"]) for result in case_results]
    queue_waits = [
        round(
            (
                datetime.fromisoformat(str(job["started_at"]))
                - datetime.fromisoformat(str(job["created_at"]))
            ).total_seconds()
            * 1000,
            6,
        )
        for job in jobs
        if job.get("started_at") is not None
    ]
    attempts_by_job: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_job[str(attempt["job_id"])].append(attempt)
    retry_queue_waits = []
    for job_attempts in attempts_by_job.values():
        ordered_attempts = sorted(
            job_attempts,
            key=lambda attempt: int(attempt["attempt_number"]),
        )
        for previous, current in zip(
            ordered_attempts,
            ordered_attempts[1:],
            strict=False,
        ):
            if previous.get("finished_at") is None:
                continue
            retry_queue_waits.append(
                round(
                    (
                        datetime.fromisoformat(str(current["started_at"]))
                        - datetime.fromisoformat(str(previous["finished_at"]))
                    ).total_seconds()
                    * 1000,
                    6,
                )
            )
    unavailable = {
        "evidence": "UNKNOWN",
        "value": None,
        "reason": "required raw collector samples were not supplied",
    }
    summary = {
        "valid_for_capacity_comparison": bool(reconciliation["valid_for_capacity_comparison"]),
        "throughput_cases_per_second": (
            len(terminal_jobs) / measurement_seconds if measurement_seconds > 0 else None
        ),
        "successful_throughput_cases_per_second": (
            len(successful_jobs) / measurement_seconds if measurement_seconds > 0 else None
        ),
        "end_to_end_ms": end_to_end_ms,
        "case_latency_ms": _verified_distribution(case_latencies),
        "queue_wait_ms": _verified_distribution(queue_waits),
        "retry_queue_wait_ms": _verified_distribution(retry_queue_waits),
        "retry_count": int(reconciliation["retry_count"]),
        "claim_latency_ms": dict(unavailable),
        "db_transaction_latency_ms": dict(unavailable),
        "db_lock_wait": dict(unavailable),
        "cpu_rss": dict(unavailable),
        "postgres_connections": dict(unavailable),
        "redis_publish_failures": dict(unavailable),
        "stale_submission_rejection": {
            "evidence": "NOT_RUN",
            "observed": 0,
        },
    }
    samples = collector_samples or {}
    claim_latencies = [float(value) for value in samples.get("claim_latency_ms", ())]
    if claim_latencies:
        summary["claim_latency_ms"] = _verified_distribution(claim_latencies)
    transaction_latencies = [float(value) for value in samples.get("db_transaction_latency_ms", ())]
    if transaction_latencies:
        summary["db_transaction_latency_ms"] = _verified_distribution(transaction_latencies)
    lock_waiters = [int(value) for value in samples.get("db_lock_waiting_connections", ())]
    if lock_waiters:
        summary["db_lock_wait"] = {
            "evidence": "DIRECTIONAL",
            "sample_count": len(lock_waiters),
            "samples_with_waiters": sum(value > 0 for value in lock_waiters),
            "peak_waiting_connections": max(lock_waiters),
        }
    cpu_percent = [float(value) for value in samples.get("cpu_percent", ())]
    rss_bytes = [int(value) for value in samples.get("rss_bytes", ())]
    if cpu_percent and rss_bytes:
        summary["cpu_rss"] = {
            "evidence": "VERIFIED",
            "sample_count": min(len(cpu_percent), len(rss_bytes)),
            "cpu_percent_peak": max(cpu_percent),
            "rss_bytes_peak": max(rss_bytes),
        }
    connection_counts = [int(value) for value in samples.get("postgres_connections", ())]
    if connection_counts:
        summary["postgres_connections"] = {
            "evidence": "VERIFIED",
            "sample_count": len(connection_counts),
            "peak": max(connection_counts),
        }
    redis_failures = [float(value) for value in samples.get("redis_publish_failures", ())]
    if redis_failures:
        summary["redis_publish_failures"] = {
            "evidence": "VERIFIED",
            "sample_count": len(redis_failures),
            "delta": redis_failures[-1] - redis_failures[0],
        }
    return summary


def merge_prometheus_evidence(
    *,
    summary: Mapping[str, Any],
    prometheus_delta: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach Prometheus evidence and fail closed on required collection gaps."""
    merged = dict(summary)
    db_operations = prometheus_delta["db_operations"]
    merged["claim_latency_ms"] = dict(db_operations["claim"])
    merged["db_transaction_latency_ms"] = {
        operation: dict(db_operations[operation]) for operation in ("result", "failure", "reaper")
    }
    merged["redis_publish_failures"] = dict(prometheus_delta["redis_publish_failures"])
    if not bool(prometheus_delta["required_metrics_complete"]):
        merged["valid_for_capacity_comparison"] = False
    return merged


def _arm_contract(arm: object, *, label: str) -> tuple[str, str, int, int]:
    if not isinstance(arm, Mapping):
        raise ExperimentError(f"Gate 1 {label} arm must be an object")
    arm_id = arm.get("arm_id")
    workload = arm.get("workload")
    workers = arm.get("workers")
    repetition = arm.get("repetition")
    if (
        not isinstance(arm_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", arm_id) is None
        or not isinstance(workload, str)
        or not workload
        or type(workers) is not int
        or workers < 1
        or type(repetition) is not int
        or repetition < 1
    ):
        raise ExperimentError(f"Gate 1 {label} arm contract is invalid")
    return arm_id, workload, workers, repetition


def _index_expected_arms(
    expected_arms: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, str, int, int]]:
    indexed: dict[str, tuple[str, str, int, int]] = {}
    coordinates: set[tuple[str, int, int]] = set()
    for arm in expected_arms:
        contract = _arm_contract(arm, label="expected")
        arm_id, workload, workers, repetition = contract
        coordinate = (workload, workers, repetition)
        if arm_id in indexed or coordinate in coordinates:
            raise ExperimentError("Gate 1 expected arm contract contains duplicates")
        indexed[arm_id] = contract
        coordinates.add(coordinate)
    if not indexed:
        raise ExperimentError("Gate 1 expected arm contract must not be empty")
    return indexed


def evaluate_gate1_gate_flags(
    records: Sequence[dict[str, Any]],
    *,
    expected_arms: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate objective quality evidence without making a deployment decision."""
    expected = _index_expected_arms(expected_arms)
    observed: dict[str, tuple[str, str, int, int]] = {}
    valid_by_arm_id: dict[str, bool] = {}
    for record in records:
        contract = _arm_contract(record.get("arm"), label="observed")
        arm_id = contract[0]
        if arm_id in observed:
            raise ExperimentError("Gate 1 observed arm contract contains duplicates")
        summary = record.get("summary")
        valid = (
            summary.get("valid_for_capacity_comparison") if isinstance(summary, Mapping) else None
        )
        if type(valid) is not bool:
            raise ExperimentError("Gate 1 observed arm quality flag is invalid")
        observed[arm_id] = contract
        valid_by_arm_id[arm_id] = valid

    unexpected = sorted(set(observed) - set(expected))
    if unexpected:
        raise ExperimentError(f"Gate 1 observed unexpected arm_ids: {', '.join(unexpected)}")
    mismatched = sorted(
        arm_id for arm_id, contract in observed.items() if contract != expected[arm_id]
    )
    if mismatched:
        raise ExperimentError(f"Gate 1 observed arm contract mismatch: {', '.join(mismatched)}")

    missing = [arm_id for arm_id in expected if arm_id not in observed]
    invalid = [arm_id for arm_id in expected if valid_by_arm_id.get(arm_id) is False]
    if invalid:
        quality_status = "FAILED"
        blocked_by = ["quality_gate_failed"]
    elif missing:
        quality_status = "UNKNOWN"
        blocked_by = ["quality_gate_unknown"]
    else:
        quality_status = "VERIFIED"
        blocked_by = []
    return {
        "policy_version": GATE1_GATE_POLICY_VERSION,
        "quality_gate": {
            "status": quality_status,
            "policy": GATE1_QUALITY_GATE_POLICY,
            "expected_arm_count": len(expected),
            "observed_arm_count": len(observed),
            "expected_arms_complete": not missing,
            "missing_arm_ids": missing,
            "invalid_arm_ids": invalid,
        },
        "adoption_gate": {
            "status": "NOT_RUN",
            "review_readiness": (
                "READY_FOR_HUMAN_REVIEW" if quality_status == "VERIFIED" else "BLOCKED"
            ),
            "decision_owner": "human",
            "performance_thresholds_owner": "human",
            "automatic_worker_count_change": False,
            "automatic_adoption_decision": None,
            "selected_worker_count": None,
            "blocked_by": blocked_by,
        },
    }


def aggregate_arm_summaries(
    records: Sequence[dict[str, Any]],
    *,
    expected_arms: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_expected_arms = (
        expected_arms if expected_arms is not None else [record["arm"] for record in records]
    )
    gate_evaluation = evaluate_gate1_gate_flags(
        records,
        expected_arms=resolved_expected_arms,
    )
    grouped: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        arm = record["arm"]
        grouped[(str(arm["workload"]), int(arm["workers"]))].append(record)
    groups: list[dict[str, Any]] = []
    for (workload, workers), group_records in sorted(grouped.items()):
        ordered = sorted(
            group_records,
            key=lambda record: int(record["arm"]["repetition"]),
        )
        points = [
            float(record["summary"]["throughput_cases_per_second"])
            for record in ordered
            if record["summary"]["valid_for_capacity_comparison"]
            and record["summary"]["throughput_cases_per_second"] is not None
        ]
        groups.append(
            {
                "workload": workload,
                "workers": workers,
                "arm_ids": [str(record["arm"]["arm_id"]) for record in ordered],
                "valid_arm_count": len(points),
                "throughput_cases_per_second": {
                    "points": points,
                    "median": median(points) if points else None,
                    "min": min(points) if points else None,
                    "max": max(points) if points else None,
                },
            }
        )
    negative_scaling: list[dict[str, Any]] = []
    for workload in sorted({str(group["workload"]) for group in groups}):
        workload_groups = [
            group
            for group in groups
            if group["workload"] == workload
            and group["throughput_cases_per_second"]["median"] is not None
        ]
        for previous, current in zip(
            workload_groups,
            workload_groups[1:],
            strict=False,
        ):
            change = (
                current["throughput_cases_per_second"]["median"]
                - previous["throughput_cases_per_second"]["median"]
            )
            if change < 0:
                negative_scaling.append(
                    {
                        "workload": workload,
                        "from_workers": previous["workers"],
                        "to_workers": current["workers"],
                        "median_throughput_change": change,
                    }
                )
    return {
        "schema_version": GATE1_RESULT_SCHEMA_VERSION,
        "groups": groups,
        "negative_scaling": negative_scaling,
        "gate_evaluation": gate_evaluation,
        "automatic_adoption_decision": None,
    }
