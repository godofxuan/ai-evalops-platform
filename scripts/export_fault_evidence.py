import argparse
import csv
import json
import statistics
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from scripts.fault_bundle import validate_fault_bundle
from scripts.fault_matrix_evidence import FaultEvidenceError, validate_fault_matrix


class EvidenceAdmissionError(RuntimeError):
    """The retained fault bundle cannot support a verified correctness claim."""


Scalar = str | int | float | bool
EvidenceRecord = dict[str, Any]


@dataclass(frozen=True, slots=True)
class NormalizedFaultEvidence:
    run_id: str
    source_commit: str
    phase: str
    result_rows: tuple[dict[str, Scalar], ...]
    summary_rows: tuple[dict[str, Scalar], ...]


def normalize_verified_fault_evidence(
    manifest: EvidenceRecord,
    report: EvidenceRecord,
    *,
    phase: str,
) -> NormalizedFaultEvidence:
    if phase not in {"before", "after"}:
        raise EvidenceAdmissionError("fault evidence phase must be before or after")
    if manifest.get("status") != "complete":
        raise EvidenceAdmissionError("fault manifest is not complete")
    if report.get("status") != "verified":
        raise EvidenceAdmissionError("fault report is not verified")

    run_id = _required_string(manifest, "run_id")
    source_commit = _required_string(manifest, "source_commit")
    configuration = report.get("configuration")
    results = report.get("results")
    if not isinstance(configuration, dict) or not isinstance(results, list):
        raise EvidenceAdmissionError("fault report structure is malformed")
    report_source_commit = _required_string(configuration, "source_commit")
    repetitions = _positive_int(configuration.get("repetitions"), "repetitions")
    if source_commit != report_source_commit:
        raise EvidenceAdmissionError("fault manifest and report source commits differ")
    if manifest.get("repetitions") != repetitions:
        raise EvidenceAdmissionError("fault manifest repetition count differs from report")
    if manifest.get("scenario_count") != len(results):
        raise EvidenceAdmissionError("fault manifest scenario count differs from report")
    try:
        validate_fault_matrix(results, repetitions=repetitions)
    except (FaultEvidenceError, TypeError, ValueError) as error:
        raise EvidenceAdmissionError("fault matrix validation failed") from error

    started_at = _required_string(report, "started_at")
    result_rows: list[dict[str, Scalar]] = []
    for record in results:
        if not isinstance(record, dict):
            raise EvidenceAdmissionError("fault result is not an object")
        scenario_id = _required_string(record, "scenario_id")
        scenario = _required_string(record, "scenario")
        repetition = _positive_int(record.get("repetition"), "repetition")
        recovery_seconds = _nonnegative_float(record.get("recovery_seconds"), "recovery_seconds")
        counts = {
            name: _nonnegative_int(record.get(name), name)
            for name in (
                "submitted_count",
                "unique_job_count",
                "completed_count",
                "succeeded_count",
                "failed_count",
                "lost_count",
                "retry_count",
                "duplicate_case_result_count",
                "duplicate_terminal_commit_count",
                "stale_result_attempted_count",
                "stale_result_accepted_count",
                "stale_failure_attempted_count",
                "stale_failure_accepted_count",
                "orphan_running_count",
            )
        }
        submitted = counts["submitted_count"]
        correctness_violations = sum(
            counts[name]
            for name in (
                "failed_count",
                "lost_count",
                "duplicate_case_result_count",
                "duplicate_terminal_commit_count",
                "stale_result_accepted_count",
                "stale_failure_accepted_count",
                "orphan_running_count",
            )
        )
        if (
            record.get("invariants_passed") is not True
            or counts["unique_job_count"] != submitted
            or counts["completed_count"] != submitted
            or counts["succeeded_count"] != submitted
            or correctness_violations != 0
        ):
            raise EvidenceAdmissionError(
                f"{scenario_id}/r{repetition}: correctness evidence is not clean"
            )
        result_rows.append(
            {
                "evidence_status": "VERIFIED",
                "phase": phase,
                "evidence_run_id": run_id,
                "scenario_id": scenario_id,
                "scenario": scenario,
                "repetition": repetition,
                "source_commit": source_commit,
                "started_at": started_at,
                "recovery_seconds": recovery_seconds,
                **counts,
                "invariants_passed": True,
                "worker_container_changed": bool(record.get("worker_container_changed", False)),
                "worker_restart_required": bool(record.get("worker_restart_required", False)),
                "outage_seconds": _optional_nonnegative_float(record, "outage_seconds"),
                "outbox_pending_before_recovery": _optional_nonnegative_int(
                    record, "outbox_pending_before_recovery"
                ),
                "outbox_peak_pending_after_redis_start": _optional_nonnegative_int(
                    record, "outbox_peak_pending_after_redis_start"
                ),
                "logical_lease_seconds": _optional_nonnegative_float(
                    record, "logical_lease_seconds"
                ),
                "logical_recovery_eligibility_seconds": _optional_nonnegative_float(
                    record, "logical_recovery_eligibility_seconds"
                ),
                "reaped_count": _optional_nonnegative_int(record, "reaped_count"),
                "unique_reaped_count": _optional_nonnegative_int(record, "unique_reaped_count"),
                "http_request_count": _optional_nonnegative_int(record, "http_request_count"),
                "http_success_count": _optional_nonnegative_int(record, "http_success_count"),
                "http_error_count": _optional_nonnegative_int(record, "http_error_count"),
                "unique_run_count": _optional_nonnegative_int(record, "unique_run_count"),
                "raw_evidence_path": f"docs/results/fault/{run_id}/report.json",
            }
        )

    result_rows.sort(key=lambda row: (str(row["scenario_id"]), int(row["repetition"])))
    summary_rows = _build_summary_rows(
        result_rows,
        run_id=run_id,
        source_commit=source_commit,
        phase=phase,
        repetitions=repetitions,
    )
    return NormalizedFaultEvidence(
        run_id=run_id,
        source_commit=source_commit,
        phase=phase,
        result_rows=tuple(result_rows),
        summary_rows=tuple(summary_rows),
    )


def load_verified_fault_evidence(
    bundle_directory: Path,
    *,
    phase: str,
) -> NormalizedFaultEvidence:
    try:
        manifest = validate_fault_bundle(bundle_directory)
    except FaultEvidenceError as error:
        raise EvidenceAdmissionError("fault bundle validation failed") from error
    report = _read_json(bundle_directory / "report.json")
    return normalize_verified_fault_evidence(manifest, report, phase=phase)


def write_csv(path: Path, rows: tuple[dict[str, Scalar], ...]) -> None:
    if not rows:
        raise EvidenceAdmissionError("refusing to write an empty verified CSV")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8", newline="\n")


def _build_summary_rows(
    result_rows: list[dict[str, Scalar]],
    *,
    run_id: str,
    source_commit: str,
    phase: str,
    repetitions: int,
) -> list[dict[str, Scalar]]:
    summaries: list[dict[str, Scalar]] = []
    for scenario_id in "ABCDEFGHI":
        selected = [row for row in result_rows if row["scenario_id"] == scenario_id]
        if len(selected) != repetitions:
            raise EvidenceAdmissionError(f"scenario {scenario_id}: incomplete repetition set")
        recoveries = [float(row["recovery_seconds"]) for row in selected]
        summaries.append(
            {
                "evidence_status": "VERIFIED",
                "phase": phase,
                "scenario_id": scenario_id,
                "scenario": str(selected[0]["scenario"]),
                "repetitions": repetitions,
                "successful_recoveries": repetitions,
                "failed_recoveries": 0,
                "recovery_seconds_median": statistics.median(recoveries),
                "recovery_seconds_min": min(recoveries),
                "recovery_seconds_max": max(recoveries),
                "submitted_count": sum(int(row["submitted_count"]) for row in selected),
                "retry_count": sum(int(row["retry_count"]) for row in selected),
                "correctness_violations": 0,
                "worker_container_changes": sum(
                    int(bool(row["worker_container_changed"])) for row in selected
                ),
                "worker_restarts_required": sum(
                    int(bool(row["worker_restart_required"])) for row in selected
                ),
                "http_request_count": _sum_optional(selected, "http_request_count"),
                "http_success_count": _sum_optional(selected, "http_success_count"),
                "http_error_count": _sum_optional(selected, "http_error_count"),
                "unique_run_count": _sum_optional(selected, "unique_run_count"),
                "source_commit": source_commit,
                "source_evidence": f"docs/results/fault/{run_id}/report.json",
            }
        )
    return summaries


def _read_json(path: Path) -> EvidenceRecord:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceAdmissionError(f"could not read fault evidence: {path}") from error
    if not isinstance(value, dict):
        raise EvidenceAdmissionError(f"fault evidence is not an object: {path}")
    return value


def _required_string(values: EvidenceRecord, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceAdmissionError(f"missing non-empty string: {key}")
    return value


def _positive_int(value: object, name: str) -> int:
    parsed = _nonnegative_int(value, name)
    if parsed < 1:
        raise EvidenceAdmissionError(f"{name} must be positive")
    return parsed


def _nonnegative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvidenceAdmissionError(f"{name} must be a nonnegative integer")
    return value


def _nonnegative_float(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0:
        raise EvidenceAdmissionError(f"{name} must be nonnegative")
    return float(value)


def _optional_nonnegative_int(values: EvidenceRecord, name: str) -> int | str:
    value = values.get(name)
    if value is None:
        return ""
    return _nonnegative_int(value, name)


def _optional_nonnegative_float(values: EvidenceRecord, name: str) -> float | str:
    value = values.get(name)
    if value is None:
        return ""
    return _nonnegative_float(value, name)


def _sum_optional(rows: list[dict[str, Scalar]], name: str) -> int | str:
    values = [row[name] for row in rows if row[name] != ""]
    if not values:
        return ""
    return sum(int(value) for value in values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and normalize verified before/after fault evidence bundles."
    )
    parser.add_argument("before_bundle", type=Path)
    parser.add_argument("after_bundle", type=Path)
    parser.add_argument("output_directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    before = load_verified_fault_evidence(args.before_bundle, phase="before")
    after = load_verified_fault_evidence(args.after_bundle, phase="after")
    args.output_directory.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.output_directory / "FAULT_RESULTS.csv",
        before.result_rows + after.result_rows,
    )
    write_csv(
        args.output_directory / "EVALOPS_FAULT_INJECTION.csv",
        before.summary_rows + after.summary_rows,
    )
    print(
        f"normalized {len(before.result_rows) + len(after.result_rows)} verified "
        f"fault results from {before.run_id} and {after.run_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
