import argparse
import csv
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from scripts.experiment_support import write_report
from scripts.fair_capacity_evidence import (
    FAIR_CAPACITY_DISTRIBUTIONS,
    FAIR_CAPACITY_WORKER_COUNTS,
    build_fair_capacity_plan,
)

OVERHEAD_REPETITIONS: Final = 3
FORMAL_REPETITIONS: Final = 4
OVERHEAD_ARM_ID: Final = "fair-q1000-skew_20_to_1-w8-b1"
THROUGHPUT_OVERHEAD_LIMIT: Final = 0.05
CLAIM_P95_OVERHEAD_LIMIT: Final = 0.10
_ZERO_FIELDS: Final = (
    "lost_count",
    "duplicate_durable_result_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
    "empty_while_eligible",
)
_STAGE_METRICS: Final = (
    "scheduler_coordination_wait_ms",
    "tenant_permit_wait_ms",
    "job_row_wait_ms",
    "durable_sequence_wait_ms",
    "transaction_commit_ms",
    "claim_total_ms",
)


def _number(row: Mapping[str, object], field: str, *, positive: bool = False) -> float | None:
    value = row.get(field)
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0 or (positive and numeric == 0):
        return None
    return numeric


def _integer(row: Mapping[str, object], field: str) -> int | None:
    value = _number(row, field)
    return int(value) if value is not None and value.is_integer() else None


def _required_number(row: Mapping[str, object], field: str) -> float:
    value = _number(row, field)
    if value is None:
        raise ValueError(f"validated attribution row lost numeric field: {field}")
    return value


def _boolean(row: Mapping[str, object], field: str) -> bool | None:
    value = row.get(field)
    if value is True or value == "True" or value == "true" or value == "1":
        return True
    if value is False or value == "False" or value == "false" or value == "0":
        return False
    return None


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _relative_change(on_value: float, off_value: float) -> float | None:
    if off_value == 0:
        return 0.0 if on_value == 0 else None
    return on_value / off_value - 1


def _validated_repetition(
    rows: Sequence[Mapping[str, object]],
    *,
    source_commit: str,
    instrumentation_enabled: bool,
    expected_arm_ids: set[str],
) -> tuple[dict[str, Mapping[str, object]], list[str]]:
    failures: list[str] = []
    arm_ids = [str(row.get("arm_id")) for row in rows]
    if len(arm_ids) != len(set(arm_ids)):
        failures.append("duplicate_arm_id")
    if set(arm_ids) != expected_arm_ids or len(arm_ids) != len(expected_arm_ids):
        failures.append("arm_set_mismatch")
    by_arm = {str(row.get("arm_id")): row for row in rows}
    for arm_id, row in by_arm.items():
        if row.get("source_commit") != source_commit:
            failures.append(f"{arm_id}:source_commit_mismatch")
        if _boolean(row, "performance_attribution_enabled") is not instrumentation_enabled:
            failures.append(f"{arm_id}:instrumentation_mode_mismatch")
        submitted = _integer(row, "submitted_count")
        if submitted is None or submitted <= 0:
            failures.append(f"{arm_id}:submitted_count_invalid")
        for field in _ZERO_FIELDS:
            if _integer(row, field) != 0:
                failures.append(f"{arm_id}:{field}_nonzero_or_invalid")
        for field in (
            "jobs_per_second",
            "claim_latency_p50_ms",
            "claim_latency_p95_ms",
            "contention_retries",
            "waiting_fallbacks",
            "worker_process_cpu_percent",
            "worker_process_rss_bytes_peak",
            "job_skip_locked_miss_count",
        ):
            if _number(row, field, positive=field == "jobs_per_second") is None:
                failures.append(f"{arm_id}:{field}_invalid")
        if instrumentation_enabled:
            for metric in _STAGE_METRICS:
                if (
                    _integer(row, f"{metric}_count") is None
                    or _number(row, f"{metric}_sum") is None
                    or _number(row, f"{metric}_p50") is None
                    or _number(row, f"{metric}_p95") is None
                    or _number(row, f"{metric}_p99") is None
                ):
                    failures.append(f"{arm_id}:{metric}_invalid")
    return by_arm, failures


def _overhead_observation(row: Mapping[str, object]) -> dict[str, float]:
    return {
        "jobs_per_second": _required_number(row, "jobs_per_second"),
        "claim_latency_p95_ms": _required_number(row, "claim_latency_p95_ms"),
        "worker_process_cpu_percent": _required_number(row, "worker_process_cpu_percent"),
        "worker_process_rss_bytes_peak": _required_number(row, "worker_process_rss_bytes_peak"),
    }


def _median_observation(observations: Sequence[Mapping[str, float]]) -> dict[str, float]:
    return {
        field: statistics.median(float(row[field]) for row in observations)
        for field in observations[0]
    }


def _formal_group(
    rows: Sequence[Mapping[str, Mapping[str, object]]],
    *,
    distribution: str,
    workers: int,
) -> dict[str, Any]:
    arm_id = f"fair-q1000-{distribution}-w{workers}-b1"
    selected = [repetition[arm_id] for repetition in rows]
    submitted = [_required_number(row, "submitted_count") for row in selected]

    def med(field: str) -> float:
        return statistics.median(_required_number(row, field) for row in selected)

    stage_wait_per_success = {
        metric: statistics.median(
            _required_number(row, f"{metric}_sum") / submitted[index]
            for index, row in enumerate(selected)
        )
        for metric in _STAGE_METRICS
    }
    return {
        "arm_id": arm_id,
        "distribution": distribution,
        "worker_concurrency": workers,
        "jobs_per_second_median": med("jobs_per_second"),
        "claim_latency_p50_ms_median": med("claim_latency_p50_ms"),
        "claim_latency_p95_ms_median": med("claim_latency_p95_ms"),
        "contention_retry_per_success": statistics.median(
            _required_number(row, "contention_retries") / submitted[index]
            for index, row in enumerate(selected)
        ),
        "waiting_fallback_per_success": statistics.median(
            _required_number(row, "waiting_fallbacks") / submitted[index]
            for index, row in enumerate(selected)
        ),
        "job_skip_locked_miss_per_success": statistics.median(
            _required_number(row, "job_skip_locked_miss_count") / submitted[index]
            for index, row in enumerate(selected)
        ),
        "stage_wait_per_success_ms": stage_wait_per_success,
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return math.inf if numerator > 0 else 1.0
    return numerator / denominator


def assess_instrumentation_overhead(
    *,
    off_repetitions: Sequence[Sequence[Mapping[str, object]]],
    on_repetitions: Sequence[Sequence[Mapping[str, object]]],
    source_commit: str,
    overhead_arm_only: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    if len(off_repetitions) != OVERHEAD_REPETITIONS:
        failures.append("overhead_off_repetition_count_mismatch")
    if len(on_repetitions) != OVERHEAD_REPETITIONS:
        failures.append("overhead_on_repetition_count_mismatch")
    validated_off: list[dict[str, Mapping[str, object]]] = []
    validated_on: list[dict[str, Mapping[str, object]]] = []
    expected_overhead_arm_ids = (
        {OVERHEAD_ARM_ID}
        if overhead_arm_only
        else {arm.arm_id for arm in build_fair_capacity_plan(queue_sizes=(1_000,))}
    )
    for label, repetitions, enabled, target in (
        ("off", off_repetitions, False, validated_off),
        ("on", on_repetitions, True, validated_on),
    ):
        for index, rows in enumerate(repetitions, start=1):
            by_arm, repetition_failures = _validated_repetition(
                rows,
                source_commit=source_commit,
                instrumentation_enabled=enabled,
                expected_arm_ids=expected_overhead_arm_ids,
            )
            target.append(by_arm)
            failures.extend(f"{label}{index}:{failure}" for failure in repetition_failures)
    if failures:
        return {
            "schema_version": 1,
            "status": "FAILED",
            "source_commit": source_commit,
            "failures": failures,
            "overhead": None,
        }

    off_observations = [_overhead_observation(rows[OVERHEAD_ARM_ID]) for rows in validated_off]
    on_observations = [_overhead_observation(rows[OVERHEAD_ARM_ID]) for rows in validated_on]
    off_median = _median_observation(off_observations)
    on_median = _median_observation(on_observations)
    throughput_change = _relative_change(
        on_median["jobs_per_second"], off_median["jobs_per_second"]
    )
    claim_p95_change = _relative_change(
        on_median["claim_latency_p95_ms"], off_median["claim_latency_p95_ms"]
    )
    overhead_valid = (
        throughput_change is not None
        and claim_p95_change is not None
        and abs(throughput_change) <= THROUGHPUT_OVERHEAD_LIMIT
        and abs(claim_p95_change) <= CLAIM_P95_OVERHEAD_LIMIT
    )
    overhead = {
        "status": "VALID" if overhead_valid else "INSTRUMENTATION_TOO_INTRUSIVE",
        "arm_id": OVERHEAD_ARM_ID,
        "off_observations": off_observations,
        "on_observations": on_observations,
        "off_median": off_median,
        "on_median": on_median,
        "throughput_relative_change": throughput_change,
        "claim_p95_relative_change": claim_p95_change,
        "cpu_relative_change": _relative_change(
            on_median["worker_process_cpu_percent"], off_median["worker_process_cpu_percent"]
        ),
        "rss_relative_change": _relative_change(
            on_median["worker_process_rss_bytes_peak"],
            off_median["worker_process_rss_bytes_peak"],
        ),
    }
    return {
        "schema_version": 1,
        "status": overhead["status"],
        "source_commit": source_commit,
        "failures": [] if overhead_valid else ["instrumentation_overhead_exceeded"],
        "overhead": overhead,
    }


def assess_performance_attribution(
    *,
    off_repetitions: Sequence[Sequence[Mapping[str, object]]],
    on_repetitions: Sequence[Sequence[Mapping[str, object]]],
    formal_repetitions: Sequence[Sequence[Mapping[str, object]]],
    source_commit: str,
    overhead_arm_only: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    if len(off_repetitions) != OVERHEAD_REPETITIONS:
        failures.append("overhead_off_repetition_count_mismatch")
    if len(on_repetitions) != OVERHEAD_REPETITIONS:
        failures.append("overhead_on_repetition_count_mismatch")
    if len(formal_repetitions) != FORMAL_REPETITIONS:
        failures.append("formal_repetition_count_mismatch")

    validated_off: list[dict[str, Mapping[str, object]]] = []
    validated_on: list[dict[str, Mapping[str, object]]] = []
    validated_formal: list[dict[str, Mapping[str, object]]] = []
    full_arm_ids = {arm.arm_id for arm in build_fair_capacity_plan(queue_sizes=(1_000,))}
    expected_overhead_arm_ids = {OVERHEAD_ARM_ID} if overhead_arm_only else full_arm_ids
    for label, repetitions, enabled, target in (
        ("off", off_repetitions, False, validated_off),
        ("on", on_repetitions, True, validated_on),
        ("formal", formal_repetitions, True, validated_formal),
    ):
        for index, rows in enumerate(repetitions, start=1):
            by_arm, repetition_failures = _validated_repetition(
                rows,
                source_commit=source_commit,
                instrumentation_enabled=enabled,
                expected_arm_ids=(full_arm_ids if label == "formal" else expected_overhead_arm_ids),
            )
            target.append(by_arm)
            failures.extend(f"{label}{index}:{failure}" for failure in repetition_failures)

    if failures:
        return {
            "schema_version": 1,
            "status": "FAILED",
            "source_commit": source_commit,
            "failures": failures,
            "overhead": None,
            "groups": [],
            "hypotheses": {},
        }

    off_observations = [_overhead_observation(rows[OVERHEAD_ARM_ID]) for rows in validated_off]
    on_observations = [_overhead_observation(rows[OVERHEAD_ARM_ID]) for rows in validated_on]
    off_median = _median_observation(off_observations)
    on_median = _median_observation(on_observations)
    throughput_change = _relative_change(
        on_median["jobs_per_second"], off_median["jobs_per_second"]
    )
    claim_p95_change = _relative_change(
        on_median["claim_latency_p95_ms"], off_median["claim_latency_p95_ms"]
    )
    overhead_valid = (
        throughput_change is not None
        and claim_p95_change is not None
        and abs(throughput_change) <= THROUGHPUT_OVERHEAD_LIMIT
        and abs(claim_p95_change) <= CLAIM_P95_OVERHEAD_LIMIT
    )
    overhead = {
        "status": "VALID" if overhead_valid else "INSTRUMENTATION_TOO_INTRUSIVE",
        "arm_id": OVERHEAD_ARM_ID,
        "off_observations": off_observations,
        "on_observations": on_observations,
        "off_median": off_median,
        "on_median": on_median,
        "throughput_relative_change": throughput_change,
        "claim_p95_relative_change": claim_p95_change,
        "cpu_relative_change": _relative_change(
            on_median["worker_process_cpu_percent"], off_median["worker_process_cpu_percent"]
        ),
        "rss_relative_change": _relative_change(
            on_median["worker_process_rss_bytes_peak"],
            off_median["worker_process_rss_bytes_peak"],
        ),
    }
    if not overhead_valid:
        return {
            "schema_version": 1,
            "status": "INSTRUMENTATION_TOO_INTRUSIVE",
            "source_commit": source_commit,
            "failures": ["instrumentation_overhead_exceeded"],
            "overhead": overhead,
            "groups": [],
            "hypotheses": {},
        }

    groups = [
        _formal_group(
            validated_formal,
            distribution=distribution,
            workers=workers,
        )
        for distribution in FAIR_CAPACITY_DISTRIBUTIONS
        for workers in FAIR_CAPACITY_WORKER_COUNTS
    ]
    by_group = {
        (str(group["distribution"]), int(group["worker_concurrency"])): group for group in groups
    }
    failing_distributions = (
        "single_tenant",
        "balanced_multi_tenant",
        "skew_20_to_1",
    )
    h1_details: list[dict[str, Any]] = []
    h2_details: list[dict[str, Any]] = []
    h3_details: list[dict[str, Any]] = []
    for distribution in FAIR_CAPACITY_DISTRIBUTIONS:
        w4 = by_group[(distribution, 4)]
        w8 = by_group[(distribution, 8)]
        singleton4 = float(w4["stage_wait_per_success_ms"]["scheduler_coordination_wait_ms"])
        singleton8 = float(w8["stage_wait_per_success_ms"]["scheduler_coordination_wait_ms"])
        latency_increase = float(w8["claim_latency_p50_ms_median"]) - float(
            w4["claim_latency_p50_ms_median"]
        )
        singleton_increase = singleton8 - singleton4
        h1_details.append(
            {
                "distribution": distribution,
                "w8_to_w4_wait_ratio": _ratio(singleton8, singleton4),
                "claim_latency_increase_ms": latency_increase,
                "singleton_wait_increase_ms": singleton_increase,
                "latency_increase_share": (
                    singleton_increase / latency_increase if latency_increase > 0 else None
                ),
            }
        )
        permit4 = float(w4["stage_wait_per_success_ms"]["tenant_permit_wait_ms"])
        permit8 = float(w8["stage_wait_per_success_ms"]["tenant_permit_wait_ms"])
        h2_details.append(
            {
                "distribution": distribution,
                "w4_wait_per_success_ms": permit4,
                "w8_wait_per_success_ms": permit8,
                "increase_ms": permit8 - permit4,
            }
        )
        miss4 = float(w4["job_skip_locked_miss_per_success"])
        miss8 = float(w8["job_skip_locked_miss_per_success"])
        h3_details.append(
            {
                "distribution": distribution,
                "w8_to_w4_miss_ratio": _ratio(miss8, miss4),
                "miss_increase": miss8 - miss4,
                "retry_increase": float(w8["contention_retry_per_success"])
                - float(w4["contention_retry_per_success"]),
                "fallback_increase": float(w8["waiting_fallback_per_success"])
                - float(w4["waiting_fallback_per_success"]),
                "claim_latency_increase_ms": latency_increase,
            }
        )

    h1_supported = [
        row
        for row in h1_details
        if row["distribution"] in failing_distributions
        and row["w8_to_w4_wait_ratio"] is not None
        and float(row["w8_to_w4_wait_ratio"]) >= 2
        and row["latency_increase_share"] is not None
        and float(row["latency_increase_share"]) >= 0.25
    ]
    h1_many = next(row for row in h1_details if row["distribution"] == "many_small_tenants")
    h1_many_equivalent = (
        h1_many["w8_to_w4_wait_ratio"] is not None
        and float(h1_many["w8_to_w4_wait_ratio"]) >= 2
        and h1_many["latency_increase_share"] is not None
        and float(h1_many["latency_increase_share"]) >= 0.25
    )
    h1_status = (
        "SUPPORTED" if len(h1_supported) >= 2 and not h1_many_equivalent else "NOT_SUPPORTED"
    )

    h2_failing_growth = [
        float(row["increase_ms"])
        for row in h2_details
        if row["distribution"] in failing_distributions
    ]
    h2_many_growth = float(
        next(row for row in h2_details if row["distribution"] == "many_small_tenants")[
            "increase_ms"
        ]
    )
    h2_status = (
        "SUPPORTED"
        if all(growth > 0 for growth in h2_failing_growth)
        and min(h2_failing_growth) > h2_many_growth
        else "NOT_SUPPORTED"
    )

    h3_supported = [
        row
        for row in h3_details
        if row["distribution"] in failing_distributions
        and row["w8_to_w4_miss_ratio"] is not None
        and float(row["w8_to_w4_miss_ratio"]) >= 2
        and float(row["retry_increase"]) > 0
        and float(row["fallback_increase"]) > 0
        and float(row["claim_latency_increase_ms"]) > 0
    ]
    h3_status = "SUPPORTED" if len(h3_supported) >= 2 else "REJECTED"

    return {
        "schema_version": 1,
        "status": "ATTRIBUTION_COMPLETE",
        "source_commit": source_commit,
        "failures": [],
        "overhead": overhead,
        "groups": groups,
        "hypotheses": {
            "H1_scheduler_coordination_singleton": {
                "status": h1_status,
                "details": h1_details,
            },
            "H2_tenant_permit_contention": {"status": h2_status, "details": h2_details},
            "H3_skip_locked_retry_feedback": {"status": h3_status, "details": h3_details},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assess preregistered scheduler contention attribution."
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--off-csv", action="append", type=Path, required=True)
    parser.add_argument("--on-csv", action="append", type=Path, required=True)
    parser.add_argument("--formal-csv", action="append", type=Path, default=[])
    parser.add_argument("--overhead-only", action="store_true")
    parser.add_argument(
        "--overhead-arm-only",
        action="store_true",
        help="require each OFF/ON repetition to contain only the registered overhead arm",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    off_repetitions = [_read_csv(path) for path in args.off_csv]
    on_repetitions = [_read_csv(path) for path in args.on_csv]
    assessment = (
        assess_instrumentation_overhead(
            off_repetitions=off_repetitions,
            on_repetitions=on_repetitions,
            source_commit=str(args.source_commit),
            overhead_arm_only=bool(args.overhead_arm_only),
        )
        if args.overhead_only
        else assess_performance_attribution(
            off_repetitions=off_repetitions,
            on_repetitions=on_repetitions,
            formal_repetitions=[_read_csv(path) for path in args.formal_csv],
            source_commit=str(args.source_commit),
            overhead_arm_only=bool(args.overhead_arm_only),
        )
    )
    write_report(args.output, assessment)
    print(f"performance attribution status: {assessment['status']}")
    return 0 if assessment["status"] in {"VALID", "ATTRIBUTION_COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
