import argparse
import csv
import json
import math
import re
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from scripts.fair_capacity_evidence import (
    FAIR_CAPACITY_DISTRIBUTIONS,
    FAIR_CAPACITY_WORKER_COUNTS,
    build_fair_capacity_plan,
    write_release_manifest,
)

TARGETED_REPETITIONS: Final = 4
TARGETED_QUEUE_SIZE: Final = 1_000
TARGETED_SELF_SCALE_FLOOR: Final = 0.95
TARGETED_METRICS: Final = (
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
    "waiting_fallbacks",
    "empty_while_eligible",
    "postgres_lock_waiting_connections_peak",
    "worker_process_cpu_percent",
    "worker_process_rss_bytes_peak",
)
_ZERO_CORRECTNESS_FIELDS: Final = (
    "lost_count",
    "duplicate_durable_result_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
)
_TARGETED_ARM_PATTERN: Final = re.compile(
    r"fair-q(?P<queue_size>[1-9][0-9]*)-"
    r"(?P<distribution>[a-z0-9_]+)-"
    r"w(?P<worker_concurrency>[1-9][0-9]*)-"
    r"b(?P<claim_batch_size>[1-9][0-9]*)"
)
_NONNEGATIVE_FLOAT_METRICS: Final = {
    "claim_latency_p50_ms",
    "claim_latency_p95_ms",
    "claim_latency_p99_ms",
    "reservation_latency_p50_ms",
    "reservation_latency_p95_ms",
    "reservation_latency_p99_ms",
    "job_claim_latency_p50_ms",
    "job_claim_latency_p95_ms",
    "job_claim_latency_p99_ms",
    "contention_retry_per_success",
    "worker_process_cpu_percent",
}
_NONNEGATIVE_INTEGER_METRICS: Final = {
    "tenant_turn_reserved",
    "tenant_turn_without_job",
    "contention_retries",
    "waiting_fallbacks",
    "empty_while_eligible",
    "postgres_lock_waiting_connections_peak",
    "worker_process_rss_bytes_peak",
}


def _number(row: Mapping[str, object], field: str) -> float | None:
    value = row.get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return None
    else:
        return None
    return numeric if math.isfinite(numeric) else None


def _integer(row: Mapping[str, object], field: str) -> int | None:
    value = _number(row, field)
    if value is None or value < 0 or not value.is_integer():
        return None
    return int(value)


def _metric_value(row: Mapping[str, object], metric: str) -> float | None:
    value = _number(row, metric)
    if value is None:
        return None
    if metric == "jobs_per_second":
        return value if value > 0 else None
    if metric == "reservation_miss_rate":
        return value if 0 <= value <= 1 else None
    if metric in _NONNEGATIVE_INTEGER_METRICS:
        return value if value >= 0 and value.is_integer() else None
    if metric in _NONNEGATIVE_FLOAT_METRICS:
        return value if value >= 0 else None
    return None


def _targeted_arm_contract(arm_id: str) -> tuple[int, str, int, int] | None:
    match = _TARGETED_ARM_PATTERN.fullmatch(arm_id)
    if match is None or match.group("distribution") not in FAIR_CAPACITY_DISTRIBUTIONS:
        return None
    return (
        int(match.group("queue_size")),
        match.group("distribution"),
        int(match.group("worker_concurrency")),
        int(match.group("claim_batch_size")),
    )


def _failed(*, source_commit: str, failures: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "FAILED",
        "source_commit": source_commit,
        "repetition_count": 0,
        "queue_size": TARGETED_QUEUE_SIZE,
        "claim_batch_size": 1,
        "self_scaling_floor": TARGETED_SELF_SCALE_FLOOR,
        "metric_contract": list(TARGETED_METRICS),
        "groups": [],
        "self_scaling": [],
        "failures": failures,
    }


def assess_targeted_repetitions(
    repetitions: Sequence[Sequence[Mapping[str, object]]],
    *,
    source_commit: str,
) -> dict[str, Any]:
    """Fail closed, then assess the repeated 1k-queue 4-to-8 scaling contract."""

    if len(repetitions) != TARGETED_REPETITIONS:
        return _failed(
            source_commit=source_commit,
            failures=["repetition_count_must_equal_4"],
        )

    expected_arm_ids = {
        arm.arm_id for arm in build_fair_capacity_plan(queue_sizes=(TARGETED_QUEUE_SIZE,))
    }
    values: dict[tuple[str, int], dict[str, list[float]]] = {
        (distribution, workers): {metric: [] for metric in TARGETED_METRICS}
        for distribution in FAIR_CAPACITY_DISTRIBUTIONS
        for workers in FAIR_CAPACITY_WORKER_COUNTS
    }
    failures: list[str] = []
    for repetition_number, rows in enumerate(repetitions, start=1):
        observed_arm_ids = [str(row.get("arm_id")) for row in rows]
        if len(observed_arm_ids) != len(set(observed_arm_ids)):
            failures.append(f"rep{repetition_number}:duplicate_arm_id")
        missing = sorted(expected_arm_ids - set(observed_arm_ids))
        extra = sorted(set(observed_arm_ids) - expected_arm_ids)
        failures.extend(f"rep{repetition_number}:missing_arm:{arm_id}" for arm_id in missing)
        failures.extend(f"rep{repetition_number}:unexpected_arm:{arm_id}" for arm_id in extra)
        for row in rows:
            arm_id = str(row.get("arm_id"))
            prefix = f"rep{repetition_number}:{arm_id}"
            if row.get("source_commit") != source_commit:
                failures.append(f"{prefix}:source_commit_mismatch")
            arm_contract = _targeted_arm_contract(arm_id)
            if arm_contract is None:
                failures.append(f"{prefix}:arm_id_invalid")
                group = None
            else:
                expected_queue, expected_distribution, expected_workers, expected_batch = (
                    arm_contract
                )
                if (
                    _integer(row, "queue_size") != expected_queue
                    or row.get("distribution") != expected_distribution
                    or _integer(row, "worker_concurrency") != expected_workers
                    or _integer(row, "claim_batch_size") != expected_batch
                ):
                    failures.append(f"{prefix}:arm_metadata_mismatch")
                group = values.get((expected_distribution, expected_workers))
            submitted = _integer(row, "submitted_count")
            if submitted is None or submitted <= 0:
                failures.append(f"{prefix}:submitted_count_invalid")
            for field in ("unique_job_count", "terminal_count"):
                if _integer(row, field) != submitted:
                    failures.append(f"{prefix}:{field}_does_not_match_submitted")
            for field in _ZERO_CORRECTNESS_FIELDS:
                if _integer(row, field) != 0:
                    failures.append(f"{prefix}:{field}_nonzero")

            for metric in TARGETED_METRICS:
                metric_value = _metric_value(row, metric)
                if metric_value is None:
                    failures.append(f"{prefix}:{metric}_invalid")
                elif group is not None:
                    group[metric].append(metric_value)

    for (distribution, workers), metric_values in values.items():
        if any(
            len(observations) != TARGETED_REPETITIONS for observations in metric_values.values()
        ):
            failures.append(f"group:{distribution}:w{workers}:observation_count_must_equal_4")

    if failures:
        failed = _failed(source_commit=source_commit, failures=failures)
        failed["repetition_count"] = len(repetitions)
        return failed

    groups: list[dict[str, Any]] = []
    for distribution in FAIR_CAPACITY_DISTRIBUTIONS:
        for workers in FAIR_CAPACITY_WORKER_COUNTS:
            metric_values = values[(distribution, workers)]
            groups.append(
                {
                    "distribution": distribution,
                    "worker_concurrency": workers,
                    "repetitions": TARGETED_REPETITIONS,
                    "median": {
                        metric: statistics.median(observations)
                        for metric, observations in metric_values.items()
                    },
                    "observations": metric_values,
                }
            )

    throughput = {
        (str(group["distribution"]), int(group["worker_concurrency"])): float(
            group["median"]["jobs_per_second"]
        )
        for group in groups
    }
    self_scaling: list[dict[str, Any]] = []
    scale_failures: list[str] = []
    for distribution in FAIR_CAPACITY_DISTRIBUTIONS:
        throughput_4 = throughput[(distribution, 4)]
        throughput_8 = throughput[(distribution, 8)]
        ratio = throughput_8 / throughput_4
        status = "VERIFIED" if ratio >= TARGETED_SELF_SCALE_FLOOR else "NEGATIVE_SCALING"
        if status == "NEGATIVE_SCALING":
            scale_failures.append(f"negative_scaling:{distribution}")
        self_scaling.append(
            {
                "distribution": distribution,
                "throughput_4_jobs_per_second": throughput_4,
                "throughput_8_jobs_per_second": throughput_8,
                "throughput_8_to_4_ratio": ratio,
                "required_minimum_ratio": TARGETED_SELF_SCALE_FLOOR,
                "status": status,
            }
        )

    return {
        "schema_version": 1,
        "status": "NEGATIVE_SCALING" if scale_failures else "VERIFIED",
        "source_commit": source_commit,
        "repetition_count": TARGETED_REPETITIONS,
        "queue_size": TARGETED_QUEUE_SIZE,
        "claim_batch_size": 1,
        "self_scaling_floor": TARGETED_SELF_SCALE_FLOOR,
        "metric_contract": list(TARGETED_METRICS),
        "groups": groups,
        "self_scaling": self_scaling,
        "failures": scale_failures,
    }


def _read_rows(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess repeated final-scheduler targeted runs.")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--input-csv", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-root", type=Path)
    args = parser.parse_args()
    assessment = assess_targeted_repetitions(
        [_read_rows(path) for path in args.input_csv if path.is_file()],
        source_commit=str(args.source_commit),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.manifest_root is not None:
        write_release_manifest(
            args.manifest_root,
            source_commit=str(args.source_commit),
            claim_scope="final_scheduler_targeted",
        )
    print(f"targeted scheduler evidence status: {assessment['status']}")
    return 0 if assessment["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
