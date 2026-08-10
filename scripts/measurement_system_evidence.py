"""Fail-closed assessment for the passive PostgreSQL measurement qualification."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

MEASUREMENT_ORDER = (
    (1, "A", "OFF", 1),
    (2, "A", "ON", 1),
    (3, "A", "ON", 2),
    (4, "A", "OFF", 2),
    (5, "B", "ON", 3),
    (6, "B", "OFF", 3),
    (7, "B", "OFF", 4),
    (8, "B", "ON", 4),
)
MEASUREMENT_ARM_ID = "fair-q1000-skew_20_to_1-w8-b1"
MEASUREMENT_SAMPLE_JOBS = 100
MEASUREMENT_SAMPLING_HZ = 5
THROUGHPUT_ABSOLUTE_PERTURBATION_LIMIT = 0.05
CLAIM_P95_ABSOLUTE_PERTURBATION_LIMIT = 0.10

_ARM_PATTERN = re.compile(
    r"fair-q(?P<queue>[1-9][0-9]*)-(?P<distribution>[a-z0-9_]+)-"
    r"w(?P<workers>[1-9][0-9]*)-b(?P<batch>[1-9][0-9]*)"
)
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_NUMERIC_FIELDS = (
    "jobs_per_second",
    "claim_latency_p50_ms",
    "claim_latency_p95_ms",
    "claim_latency_p99_ms",
    "worker_process_cpu_percent",
    "worker_process_rss_bytes_peak",
    "contention_retries",
    "contention_retry_per_success",
    "waiting_fallbacks",
    "postgres_lock_waiting_connections_peak",
    "lost_count",
    "duplicate_durable_result_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
    "empty_while_eligible",
    "telemetry_successful_sample_count",
    "telemetry_observed_wait_sample_count",
    "telemetry_observed_waiting_backends",
    "telemetry_error_count",
    "telemetry_dropped_sample_count",
    "telemetry_buffer_overflow_count",
)
_CORRECTNESS_FIELDS = (
    "lost_count",
    "duplicate_durable_result_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
    "empty_while_eligible",
)
_TELEMETRY_ZERO_FIELDS = (
    "telemetry_error_count",
    "telemetry_dropped_sample_count",
    "telemetry_buffer_overflow_count",
)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _relative_change(*, baseline: float, observed: float) -> float:
    if baseline <= 0:
        raise ValueError("relative-change baseline must be positive")
    return (observed - baseline) / baseline


def _statistics(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ValueError("statistics require observations")
    mean = statistics.fmean(values)
    median = statistics.median(values)
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum
    return {
        "min": minimum,
        "max": maximum,
        "mean": mean,
        "median": median,
        "range": spread,
        "range_over_mean": spread / mean if mean else 0.0,
        "mad": statistics.median(abs(value - median) for value in values),
    }


def verify_sealed_manifest(directory: Path) -> tuple[str, ...]:
    """Independently verify exact file set, sizes, and SHA-256 values."""
    failures: set[str] = set()
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("manifest_unreadable",)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        return ("manifest_files_invalid",)
    paths = list(directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        failures.add("manifest_symlink_present")
    actual = {
        path.relative_to(directory).as_posix(): path
        for path in paths
        if path.is_file() and path != manifest_path
    }
    listed = set(files)
    if listed - set(actual):
        failures.add("manifest_missing_files")
    if set(actual) - listed:
        failures.add("manifest_extra_files")
    for relative_path in sorted(listed & set(actual)):
        candidate = PurePosixPath(relative_path)
        entry = files[relative_path]
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or not isinstance(entry, dict)
            or not isinstance(entry.get("size_bytes"), int)
            or isinstance(entry.get("size_bytes"), bool)
            or not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            failures.add("manifest_entry_invalid")
            continue
        path = actual[relative_path]
        if path.stat().st_size != entry["size_bytes"]:
            failures.add("manifest_size_mismatch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            failures.add("manifest_hash_mismatch")
    return tuple(sorted(failures))


def _append_once(failures: list[str], failure: str) -> None:
    if failure not in failures:
        failures.append(failure)


def assess_measurement_system(
    repetitions: Sequence[Mapping[str, object]],
    *,
    expected_source_commit: str,
    expected_measurement_code_sha: str,
    expected_workflow_run_id: str,
    manifest_failures: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    failures: list[str] = []
    if len(repetitions) != len(MEASUREMENT_ORDER):
        _append_once(failures, "repetition_count_invalid")
    if _SHA_PATTERN.fullmatch(expected_source_commit) is None:
        _append_once(failures, "source_identity_invalid")
    if _SHA_PATTERN.fullmatch(expected_measurement_code_sha) is None:
        _append_once(failures, "measurement_code_identity_invalid")
    if not expected_workflow_run_id:
        _append_once(failures, "workflow_identity_invalid")

    observed_order: list[tuple[int | None, object, object, int | None]] = []
    mode_repetitions: list[tuple[object, int | None]] = []
    numeric_rows: list[dict[str, float]] = []
    for row in repetitions:
        run_id = str(row.get("run_id", ""))
        if manifest_failures.get(run_id):
            _append_once(failures, "manifest_invalid")
        if row.get("source_commit") != expected_source_commit:
            _append_once(failures, "source_identity_invalid")
        if row.get("measurement_code_sha") != expected_measurement_code_sha:
            _append_once(failures, "measurement_code_identity_invalid")
        if str(row.get("workflow_run_id", "")) != expected_workflow_run_id:
            _append_once(failures, "workflow_identity_invalid")

        arm_id = row.get("arm_id")
        arm_match = _ARM_PATTERN.fullmatch(arm_id) if isinstance(arm_id, str) else None
        if arm_match is None or arm_id != MEASUREMENT_ARM_ID:
            _append_once(failures, "arm_identity_invalid")
        expected_workload = {
            "queue_size": 1000,
            "distribution": "skew_20_to_1",
            "worker_concurrency": 8,
            "claim_batch_size": 1,
        }
        if arm_match is not None:
            expected_workload = {
                "queue_size": int(arm_match.group("queue")),
                "distribution": arm_match.group("distribution"),
                "worker_concurrency": int(arm_match.group("workers")),
                "claim_batch_size": int(arm_match.group("batch")),
            }
        for field, expected in expected_workload.items():
            observed: object = row.get(field)
            if isinstance(expected, int):
                observed = _integer(observed)
            if observed != expected:
                _append_once(failures, f"{field}_drift")
        if _integer(row.get("sample_jobs")) != MEASUREMENT_SAMPLE_JOBS:
            _append_once(failures, "sample_jobs_drift")
        if _integer(row.get("telemetry_sampling_hz")) != MEASUREMENT_SAMPLING_HZ:
            _append_once(failures, "sampling_frequency_drift")

        position = _integer(row.get("measurement_order_position"))
        mode_repetition = _integer(row.get("measurement_mode_repetition"))
        mode = row.get("measurement_mode")
        block = row.get("measurement_block")
        observed_order.append((position, block, mode, mode_repetition))
        mode_repetitions.append((mode, mode_repetition))

        numeric: dict[str, float] = {}
        for field in _NUMERIC_FIELDS:
            value = _number(row.get(field))
            if value is None:
                _append_once(failures, "numeric_domain_invalid")
            else:
                numeric[field] = value
        numeric_rows.append(numeric)
        if any(_integer(row.get(field)) != 0 for field in _CORRECTNESS_FIELDS):
            _append_once(failures, "correctness_invalid")
        if any(_integer(row.get(field)) != 0 for field in _TELEMETRY_ZERO_FIELDS):
            _append_once(failures, "telemetry_integrity_invalid")
        successful_samples = _integer(row.get("telemetry_successful_sample_count"))
        wait_samples = _integer(row.get("telemetry_observed_wait_sample_count"))
        if mode == "ON":
            if successful_samples is None or successful_samples <= 0:
                _append_once(failures, "telemetry_integrity_invalid")
            if (
                wait_samples is None
                or successful_samples is None
                or wait_samples > successful_samples
            ):
                _append_once(failures, "telemetry_integrity_invalid")
        elif mode == "OFF":
            telemetry_fields = (
                "telemetry_successful_sample_count",
                "telemetry_observed_wait_sample_count",
                "telemetry_observed_waiting_backends",
            )
            if any(_integer(row.get(field)) != 0 for field in telemetry_fields):
                _append_once(failures, "telemetry_integrity_invalid")
        else:
            _append_once(failures, "measurement_order_invalid")

    if tuple(observed_order) != MEASUREMENT_ORDER:
        _append_once(failures, "measurement_order_invalid")
    expected_mode_repetitions = [(mode, repetition) for _, _, mode, repetition in MEASUREMENT_ORDER]
    if sorted(mode_repetitions, key=str) != sorted(expected_mode_repetitions, key=str):
        _append_once(failures, "mode_repetition_identity_invalid")

    statistics_report: dict[str, dict[str, dict[str, float]]] = {}
    overhead: dict[str, float] = {}
    paired_blocks: list[dict[str, object]] = []
    metrics = ("jobs_per_second", "claim_latency_p95_ms")
    if len(numeric_rows) == len(MEASUREMENT_ORDER) and all(
        all(metric in row for metric in metrics) for row in numeric_rows
    ):
        for metric in metrics:
            by_mode = {
                mode: [
                    numeric_rows[index][metric]
                    for index, repetition in enumerate(repetitions)
                    if repetition.get("measurement_mode") == mode
                ]
                for mode in ("OFF", "ON")
            }
            if all(len(values) == 4 for values in by_mode.values()):
                statistics_report[metric] = {
                    mode: _statistics(values) for mode, values in by_mode.items()
                }
                off_median = statistics_report[metric]["OFF"]["median"]
                on_median = statistics_report[metric]["ON"]["median"]
                try:
                    overhead[f"{metric}_relative_change"] = _relative_change(
                        baseline=off_median,
                        observed=on_median,
                    )
                except ValueError:
                    _append_once(failures, "numeric_domain_invalid")
            else:
                _append_once(failures, "measurement_order_invalid")
        for first_index, second_index in ((0, 1), (2, 3), (4, 5), (6, 7)):
            pair = [repetitions[first_index], repetitions[second_index]]
            off_index = first_index if pair[0].get("measurement_mode") == "OFF" else second_index
            on_index = second_index if off_index == first_index else first_index
            paired_blocks.append(
                {
                    "positions": [first_index + 1, second_index + 1],
                    "block": repetitions[first_index].get("measurement_block"),
                    "throughput_relative_change": _relative_change(
                        baseline=numeric_rows[off_index]["jobs_per_second"],
                        observed=numeric_rows[on_index]["jobs_per_second"],
                    ),
                    "claim_p95_relative_change": _relative_change(
                        baseline=numeric_rows[off_index]["claim_latency_p95_ms"],
                        observed=numeric_rows[on_index]["claim_latency_p95_ms"],
                    ),
                }
            )

    throughput_change = overhead.get("jobs_per_second_relative_change")
    claim_p95_change = overhead.get("claim_latency_p95_ms_relative_change")
    if throughput_change is None or abs(throughput_change) > THROUGHPUT_ABSOLUTE_PERTURBATION_LIMIT:
        _append_once(failures, "throughput_perturbation_exceeded")
    if claim_p95_change is None or abs(claim_p95_change) > CLAIM_P95_ABSOLUTE_PERTURBATION_LIMIT:
        _append_once(failures, "claim_p95_perturbation_exceeded")

    status = "MEASUREMENT_SYSTEM_INVALID" if failures else "MEASUREMENT_SYSTEM_VALID"
    return {
        "schema_version": 1,
        "status": status,
        "failures": failures,
        "source_commit": expected_source_commit,
        "measurement_code_sha": expected_measurement_code_sha,
        "workflow_run_id": expected_workflow_run_id,
        "arm_id": MEASUREMENT_ARM_ID,
        "order": [
            {
                "position": position,
                "block": block,
                "mode": mode,
                "mode_repetition": repetition,
            }
            for position, block, mode, repetition in MEASUREMENT_ORDER
        ],
        "statistics": statistics_report,
        "overhead": overhead,
        "paired_block_observations": paired_blocks,
        "thresholds": {
            "absolute_throughput_relative_change_max": (
                THROUGHPUT_ABSOLUTE_PERTURBATION_LIMIT
            ),
            "absolute_claim_p95_relative_change_max": CLAIM_P95_ABSOLUTE_PERTURBATION_LIMIT,
        },
        "formal_attribution": "NOT_RUN",
        "final_decision": (
            "PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY"
            if failures
            else "QUALIFIED_FOR_FUTURE_FORMAL_ATTRIBUTION"
        ),
    }


def _read_one_row(run_directory: Path) -> dict[str, object]:
    arms_path = run_directory / "bundle" / "arms.csv"
    with arms_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise ValueError(f"measurement run must contain exactly one arm row: {run_directory}")
    return dict(rows[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", action="append", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--measurement-code-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows: list[dict[str, object]] = []
    manifest_failures: dict[str, Sequence[str]] = {}
    try:
        for run_directory in args.run_directory:
            row = _read_one_row(run_directory)
            rows.append(row)
            manifest_failures[str(row.get("run_id", ""))] = verify_sealed_manifest(
                run_directory / "bundle"
            )
        assessment = assess_measurement_system(
            rows,
            expected_source_commit=str(args.source_commit),
            expected_measurement_code_sha=str(args.measurement_code_sha),
            expected_workflow_run_id=str(args.workflow_run_id),
            manifest_failures=manifest_failures,
        )
    except Exception as error:
        assessment = {
            "schema_version": 1,
            "status": "MEASUREMENT_SYSTEM_INVALID",
            "failures": ["assessment_input_invalid"],
            "error_type": type(error).__name__,
            "formal_attribution": "NOT_RUN",
            "final_decision": "PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"measurement-system evidence status: {assessment['status']}")
    return 0 if assessment["status"] == "MEASUREMENT_SYSTEM_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
