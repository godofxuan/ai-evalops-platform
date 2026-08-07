import argparse
import csv
import json
import statistics
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from scripts.gate1_finalization import validate_gate1_final_bundle


class EvidenceAdmissionError(RuntimeError):
    """The retained evidence cannot support a verified load claim."""


Scalar = str | int | float
EvidenceRecord = dict[str, Any]


@dataclass(frozen=True, slots=True)
class NormalizedLoadEvidence:
    run_id: str
    source_commit: str
    cases_per_arm: int
    warmup_cases_per_arm: int
    arm_rows: tuple[dict[str, Scalar], ...]
    scaling_rows: tuple[dict[str, Scalar], ...]
    totals: dict[str, int]


def normalize_verified_load_evidence(
    manifest: EvidenceRecord,
    aggregate: EvidenceRecord,
    arms: list[EvidenceRecord],
    summaries: dict[str, EvidenceRecord],
    reconciliations: dict[str, EvidenceRecord],
) -> NormalizedLoadEvidence:
    quality_gate = aggregate["gate_evaluation"]["quality_gate"]
    if quality_gate.get("status") != "VERIFIED":
        raise EvidenceAdmissionError("the aggregate quality gate is not VERIFIED")
    if quality_gate.get("expected_arms_complete") is not True:
        raise EvidenceAdmissionError("the expected arm set is incomplete")
    if quality_gate.get("invalid_arm_ids") or quality_gate.get("missing_arm_ids"):
        raise EvidenceAdmissionError("the aggregate reports invalid or missing arms")
    if quality_gate.get("expected_arm_count") != len(arms):
        raise EvidenceAdmissionError("the expected arm count does not match the arm plan")
    if quality_gate.get("observed_arm_count") != len(arms):
        raise EvidenceAdmissionError("the observed arm count does not match the arm plan")

    run_id = _required_string(manifest, "run_id")
    source_commit = _required_string(manifest["provenance"], "source_commit")
    configuration = manifest["configuration"]["values"]
    cases_per_arm = _required_positive_int(configuration, "cases")
    warmup_cases_per_arm = _required_positive_int(configuration, "warmup_cases")
    expected_repetitions = _required_positive_int(configuration, "repetitions")

    rows: list[dict[str, Scalar]] = []
    totals = {
        "submitted_count": 0,
        "unique_job_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "lost_count": 0,
        "retry_count": 0,
        "duplicate_result_count": 0,
        "orphan_running_count": 0,
        "binding_mismatch_count": 0,
        "collector_missed_samples": 0,
    }
    expected_arm_ids = {str(arm["arm_id"]) for arm in arms}
    if set(summaries) != expected_arm_ids or set(reconciliations) != expected_arm_ids:
        raise EvidenceAdmissionError("summary/reconciliation arm sets do not match the plan")

    for arm in arms:
        arm_id = _required_string(arm, "arm_id")
        summary_record = summaries[arm_id]
        summary = summary_record["summary"]
        reconciliation = reconciliations[arm_id]
        if summary_record.get("arm", {}).get("arm_id") != arm_id:
            raise EvidenceAdmissionError(f"{arm_id}: summary cross-reference mismatch")
        if summary.get("valid_for_capacity_comparison") is not True:
            raise EvidenceAdmissionError(f"{arm_id}: summary is invalid")
        if reconciliation.get("valid_for_capacity_comparison") is not True:
            raise EvidenceAdmissionError(f"{arm_id}: reconciliation is invalid")
        if reconciliation.get("violations"):
            raise EvidenceAdmissionError(f"{arm_id}: reconciliation violations are present")
        if reconciliation.get("binding_mismatches"):
            raise EvidenceAdmissionError(f"{arm_id}: binding mismatches are present")

        duplicate_job_results = reconciliation.get("duplicate_result_job_ids", [])
        duplicate_case_results = reconciliation.get("duplicate_result_run_case_keys", [])
        if duplicate_job_results or duplicate_case_results:
            raise EvidenceAdmissionError(f"{arm_id}: duplicate durable results are present")

        statuses = reconciliation["status_counts"]
        submitted_count = sum(int(value) for value in statuses.values())
        terminal_count = sum(int(statuses[name]) for name in ("succeeded", "failed", "cancelled"))
        orphan_running_count = sum(
            int(statuses[name]) for name in ("queued", "running", "retry_wait", "cancelling")
        )
        attempt_sequences = reconciliation["attempt_sequences"]
        unique_job_count = len(attempt_sequences)
        lost_count = cases_per_arm - terminal_count
        if submitted_count != cases_per_arm:
            raise EvidenceAdmissionError(f"{arm_id}: submitted Job count is not fixed")
        if unique_job_count != cases_per_arm:
            raise EvidenceAdmissionError(f"{arm_id}: unique Job count is not fixed")
        if terminal_count != cases_per_arm or lost_count != 0 or orphan_running_count != 0:
            raise EvidenceAdmissionError(f"{arm_id}: nonterminal or lost Jobs are present")
        if any(
            sequence != list(range(1, len(sequence) + 1)) for sequence in attempt_sequences.values()
        ):
            raise EvidenceAdmissionError(f"{arm_id}: attempt sequence is not contiguous")

        collector_missed_samples = int(summary["collector_missed_samples"])
        if collector_missed_samples != 0:
            raise EvidenceAdmissionError(f"{arm_id}: collector samples are missing")
        resources = summary["worker_cluster_resources"]
        if resources.get("status") != "VERIFIED":
            raise EvidenceAdmissionError(f"{arm_id}: worker resource evidence is not VERIFIED")

        stale = summary["stale_submission_rejection"]
        stale_evidence = _required_string(stale, "evidence")
        stale_accepted: Scalar = ""
        if stale_evidence == "VERIFIED":
            stale_accepted = int(stale["observed"])
        elif stale_evidence != "NOT_RUN":
            raise EvidenceAdmissionError(f"{arm_id}: stale submission evidence is ambiguous")

        retry_count = int(reconciliation["retry_count"])
        duplicate_result_count = len(duplicate_job_results) + len(duplicate_case_results)
        retry_queue_wait = summary["retry_queue_wait_ms"]
        retry_queue_wait_p95: Scalar = ""
        if int(retry_queue_wait["count"]) > 0:
            retry_queue_wait_p95 = float(retry_queue_wait["p95"])
        row: dict[str, Scalar] = {
            "evidence_status": "VERIFIED",
            "evidence_run_id": run_id,
            "source_commit": source_commit,
            "workload": _required_string(arm, "workload"),
            "workers": int(arm["workers"]),
            "repetition": int(arm["repetition"]),
            "cases": cases_per_arm,
            "warmup_cases": warmup_cases_per_arm,
            "throughput_cases_per_second": float(summary["throughput_cases_per_second"]),
            "case_latency_p50_ms": float(summary["case_latency_ms"]["p50"]),
            "case_latency_p95_ms": float(summary["case_latency_ms"]["p95"]),
            "case_latency_p99_ms": float(summary["case_latency_ms"]["p99"]),
            "end_to_end_ms": float(summary["end_to_end_ms"]),
            "queue_wait_p50_ms": float(summary["queue_wait_ms"]["p50"]),
            "queue_wait_p95_ms": float(summary["queue_wait_ms"]["p95"]),
            "queue_wait_p99_ms": float(summary["queue_wait_ms"]["p99"]),
            "retry_queue_wait_p95_ms": retry_queue_wait_p95,
            "claim_transaction_mean_ms": float(summary["claim_latency_ms"]["mean_ms"]),
            "result_transaction_mean_ms": float(
                summary["db_transaction_latency_ms"]["result"]["mean_ms"]
            ),
            "db_lock_peak_waiting_connections": int(
                summary["db_lock_wait"]["peak_waiting_connections"]
            ),
            "postgres_connections_peak": int(summary["postgres_connections"]["peak"]),
            "submitted_count": submitted_count,
            "unique_job_count": unique_job_count,
            "completed_count": terminal_count,
            "retry_count": retry_count,
            "failure_count": int(statuses["failed"]),
            "lost_count": lost_count,
            "duplicate_result_count": duplicate_result_count,
            "stale_submission_evidence": stale_evidence,
            "stale_submission_accepted_count": stale_accepted,
            "orphan_running_count": orphan_running_count,
            "binding_mismatch_count": len(reconciliation["binding_mismatches"]),
            "collector_missed_samples": collector_missed_samples,
            "worker_cluster_cpu_percent_peak": float(resources["cpu_percent"]["peak"]),
            "worker_cluster_rss_bytes_peak": int(resources["rss_bytes"]["peak"]),
            "raw_evidence_path": (
                f"docs/results/load/{run_id}/final/raw/{arm_id}/reconciliation.json"
            ),
        }
        rows.append(row)
        totals["submitted_count"] += submitted_count
        totals["unique_job_count"] += unique_job_count
        totals["completed_count"] += terminal_count
        totals["failed_count"] += int(statuses["failed"])
        totals["lost_count"] += lost_count
        totals["retry_count"] += retry_count
        totals["duplicate_result_count"] += duplicate_result_count
        totals["orphan_running_count"] += orphan_running_count
        totals["binding_mismatch_count"] += len(reconciliation["binding_mismatches"])
        totals["collector_missed_samples"] += collector_missed_samples

    rows.sort(key=lambda row: (str(row["workload"]), int(row["workers"]), int(row["repetition"])))
    scaling_rows = _build_scaling_rows(
        rows,
        run_id=run_id,
        cases_per_arm=cases_per_arm,
        expected_repetitions=expected_repetitions,
    )
    return NormalizedLoadEvidence(
        run_id=run_id,
        source_commit=source_commit,
        cases_per_arm=cases_per_arm,
        warmup_cases_per_arm=warmup_cases_per_arm,
        arm_rows=tuple(rows),
        scaling_rows=tuple(scaling_rows),
        totals=totals,
    )


def load_verified_load_evidence(run_directory: Path) -> NormalizedLoadEvidence:
    manifest = _read_json(run_directory / "manifest.json")
    aggregate = _read_json(run_directory / "final" / "summary" / "aggregate.json")
    arm_order = _read_json(run_directory / "arm_order.json")
    arms = arm_order["arms"]
    summaries = {
        str(arm["arm_id"]): _read_json(
            run_directory / "final" / "summary" / f"{arm['arm_id']}.json"
        )
        for arm in arms
    }
    validate_gate1_final_bundle(
        run_directory / "final",
        list(summaries.values()),
        expected_arms=arms,
    )
    reconciliations = {
        str(arm["arm_id"]): _read_json(
            run_directory / "final" / "raw" / str(arm["arm_id"]) / "reconciliation.json"
        )
        for arm in arms
    }
    return normalize_verified_load_evidence(
        manifest,
        aggregate,
        arms,
        summaries,
        reconciliations,
    )


def write_csv(path: Path, rows: tuple[dict[str, Scalar], ...]) -> None:
    if not rows:
        raise EvidenceAdmissionError("refusing to write an empty verified CSV")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8", newline="\n")


def _build_scaling_rows(
    arm_rows: list[dict[str, Scalar]],
    *,
    run_id: str,
    cases_per_arm: int,
    expected_repetitions: int,
) -> list[dict[str, Scalar]]:
    scaling_rows: list[dict[str, Scalar]] = []
    workloads = sorted({str(row["workload"]) for row in arm_rows})
    for workload in workloads:
        worker_counts = sorted(
            {int(row["workers"]) for row in arm_rows if row["workload"] == workload}
        )
        baseline_values = [
            float(row["throughput_cases_per_second"])
            for row in arm_rows
            if row["workload"] == workload and row["workers"] == 1
        ]
        if len(baseline_values) != expected_repetitions:
            raise EvidenceAdmissionError(f"{workload}: incomplete one-worker repetitions")
        baseline = statistics.median(baseline_values)
        for workers in worker_counts:
            selected = [
                row for row in arm_rows if row["workload"] == workload and row["workers"] == workers
            ]
            if len(selected) != expected_repetitions:
                raise EvidenceAdmissionError(f"{workload}/{workers}: incomplete repetition set")
            throughputs = [float(row["throughput_cases_per_second"]) for row in selected]
            speedup = statistics.median(throughputs) / baseline
            scaling_rows.append(
                {
                    "evidence_status": "VERIFIED",
                    "workload": workload,
                    "workers": workers,
                    "repetitions": expected_repetitions,
                    "cases_per_repetition": cases_per_arm,
                    "throughput_median_cases_per_second": statistics.median(throughputs),
                    "throughput_min_cases_per_second": min(throughputs),
                    "throughput_max_cases_per_second": max(throughputs),
                    "speedup_vs_one_worker": speedup,
                    "parallel_efficiency": speedup / workers,
                    "latency_p95_median_ms": statistics.median(
                        float(row["case_latency_p95_ms"]) for row in selected
                    ),
                    "end_to_end_median_ms": statistics.median(
                        float(row["end_to_end_ms"]) for row in selected
                    ),
                    "source_run_id": run_id,
                }
            )
    return scaling_rows


def _read_json(path: Path) -> EvidenceRecord:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceAdmissionError(f"expected a JSON object: {path}")
    return value


def _required_string(values: EvidenceRecord, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceAdmissionError(f"missing non-empty string: {key}")
    return value


def _required_positive_int(values: EvidenceRecord, key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EvidenceAdmissionError(f"missing positive integer: {key}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and normalize a verified Gate 1 load evidence bundle."
    )
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    normalized = load_verified_load_evidence(args.run_directory)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_directory / "LOAD_RESULTS.csv", normalized.arm_rows)
    write_csv(args.output_directory / "EVALOPS_SCALING.csv", normalized.scaling_rows)
    print(f"normalized {len(normalized.arm_rows)} verified arms from {normalized.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
