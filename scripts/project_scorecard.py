"""Build and verify the evidence-backed project scorecard.

The scorecard deliberately has no weighted numeric total.  A contract test, a
formal quality experiment, and a production SLO are different evidence classes
and must not compensate for one another.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from app.agent_eval.evaluators import registered_agent_evaluators
from app.observability.metrics import PlatformMetrics
from scripts.verify_final_evidence_manifest import verify_cross_repository_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORECARD_PATH = PROJECT_ROOT / "docs/review/PROJECT_SCORECARD.json"
SCORECARD_MARKDOWN_PATH = PROJECT_ROOT / "docs/review/PROJECT_SCORECARD.md"
FINAL_PAIR_PATH = (
    PROJECT_ROOT / "docs/review/evidence/final_pair_2065e571_4040fa1d/result-manifest.json"
)
CROSS_MANIFEST_PATH = PROJECT_ROOT / "docs/review/FINAL_CROSS_REPO_EVIDENCE_MANIFEST.json"
FINAL_EVIDENCE_PATH = PROJECT_ROOT / "docs/review/FINAL_EVIDENCE_MANIFEST.json"
SCHEDULER_ROOT = PROJECT_ROOT / "docs/results/release/v0.1.0/targeted-gh-31352270523-1"
SCHEDULER_ASSESSMENT_PATH = SCHEDULER_ROOT / "assessment.json"
SCHEDULER_MANIFEST_PATH = SCHEDULER_ROOT / "manifest.json"
PROTECTED_COUNTERS = (
    "lost_count",
    "duplicate_durable_result_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
)


class ScorecardEvidenceError(ValueError):
    """An authoritative scorecard input is absent, malformed, or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScorecardEvidenceError(f"cannot read JSON evidence: {path}") from error
    if not isinstance(value, dict):
        raise ScorecardEvidenceError(f"JSON evidence is not an object: {path}")
    return cast(dict[str, Any], value)


def _canonical_digest(value: Mapping[str, Any], *, exclude: str | None = None) -> str:
    payload = dict(value)
    if exclude is not None:
        payload.pop(exclude, None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_manifest_file(root: Path, manifest: Mapping[str, Any], relative: str) -> Path:
    records = manifest.get("files")
    if not isinstance(records, dict) or not isinstance(records.get(relative), dict):
        raise ScorecardEvidenceError(f"scheduler manifest does not bind {relative}")
    record = cast(dict[str, Any], records[relative])
    path = root / relative
    content = path.read_bytes()
    if record.get("size_bytes") != len(content):
        raise ScorecardEvidenceError(f"scheduler evidence size drift: {relative}")
    if record.get("sha256") != hashlib.sha256(content).hexdigest():
        raise ScorecardEvidenceError(f"scheduler evidence digest drift: {relative}")
    return path


def _scheduler_metrics() -> dict[str, Any]:
    manifest = _object(SCHEDULER_MANIFEST_PATH)
    assessment_path = _verify_manifest_file(SCHEDULER_ROOT, manifest, "assessment.json")
    assessment = _object(assessment_path)
    scaling = assessment.get("self_scaling")
    if not isinstance(scaling, list) or len(scaling) != 4:
        raise ScorecardEvidenceError("scheduler assessment must contain four scaling workloads")
    normalized_scaling: list[dict[str, Any]] = []
    for item in scaling:
        if not isinstance(item, dict):
            raise ScorecardEvidenceError("scheduler scaling entry is not an object")
        ratio = item.get("throughput_8_to_4_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise ScorecardEvidenceError("scheduler scaling ratio is not numeric")
        normalized_scaling.append(
            {
                "distribution": item.get("distribution"),
                "throughput_4_jobs_per_second": ratio_or_number(
                    item.get("throughput_4_jobs_per_second")
                ),
                "throughput_8_jobs_per_second": ratio_or_number(
                    item.get("throughput_8_jobs_per_second")
                ),
                "throughput_8_to_4_ratio": float(ratio),
                "required_minimum_ratio": ratio_or_number(item.get("required_minimum_ratio")),
                "status": item.get("status"),
            }
        )

    totals = {"submitted_count": 0, "unique_job_count": 0, "terminal_count": 0}
    protected = {name: 0 for name in PROTECTED_COUNTERS}
    fair_positions: list[int] = []
    legacy_positions: list[int] = []
    arm_count = 0
    for repetition in range(1, 5):
        relative = f"rep{repetition}/bundle/arms.csv"
        path = _verify_manifest_file(SCHEDULER_ROOT, manifest, relative)
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                arm_count += 1
                for name in totals:
                    totals[name] += _integer(row, name)
                for name in protected:
                    protected[name] += _integer(row, name)
                if row.get("distribution") == "skew_20_to_1":
                    fair_positions.append(_integer(row, "fair_first_secondary_tenant_position"))
                    legacy_positions.append(
                        _integer(row, "legacy_fifo_first_secondary_tenant_position")
                    )
    if arm_count != 64:
        raise ScorecardEvidenceError(f"expected 64 scheduler arms, observed {arm_count}")
    if totals != {"submitted_count": 6400, "unique_job_count": 6400, "terminal_count": 6400}:
        raise ScorecardEvidenceError(f"scheduler terminal accounting drift: {totals}")
    if any(protected.values()):
        raise ScorecardEvidenceError(f"scheduler protected counter is non-zero: {protected}")
    if fair_positions != [2] * 16 or legacy_positions != [953] * 16:
        raise ScorecardEvidenceError("frozen skew fairness positions drifted")
    groups = assessment.get("groups")
    if not isinstance(groups, list) or len(groups) != 16:
        raise ScorecardEvidenceError("scheduler assessment must contain 16 grouped summaries")
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("median"), dict):
            raise ScorecardEvidenceError("scheduler grouped summary is malformed")
        distribution = group.get("distribution")
        workers = group.get("worker_concurrency")
        if not isinstance(distribution, str) or not isinstance(workers, int):
            raise ScorecardEvidenceError("scheduler grouped summary identity is malformed")
        grouped[(distribution, workers)] = cast(dict[str, Any], group["median"])
    diagnostic_signals: list[dict[str, Any]] = []
    for item in normalized_scaling:
        distribution = cast(str, item["distribution"])
        four = grouped[(distribution, 4)]
        eight = grouped[(distribution, 8)]
        diagnostic_signals.append(
            {
                "distribution": distribution,
                "throughput_8_to_4_ratio": item["throughput_8_to_4_ratio"],
                "claim_latency_p95_multiplier": _positive_ratio(
                    eight, four, "claim_latency_p95_ms"
                ),
                "reservation_latency_p95_multiplier": _positive_ratio(
                    eight, four, "reservation_latency_p95_ms"
                ),
                "job_claim_latency_p95_multiplier": _positive_ratio(
                    eight, four, "job_claim_latency_p95_ms"
                ),
                "contention_retry_delta": _numeric(eight, "contention_retries")
                - _numeric(four, "contention_retries"),
                "waiting_fallback_delta": _numeric(eight, "waiting_fallbacks")
                - _numeric(four, "waiting_fallbacks"),
                "postgres_lock_wait_peak_delta": _numeric(
                    eight, "postgres_lock_waiting_connections_peak"
                )
                - _numeric(four, "postgres_lock_waiting_connections_peak"),
                "worker_cpu_percentage_point_delta": _numeric(eight, "worker_process_cpu_percent")
                - _numeric(four, "worker_process_cpu_percent"),
                "worker_rss_ratio": _positive_ratio(eight, four, "worker_process_rss_bytes_peak"),
            }
        )
    return {
        "assessment_status": assessment.get("status"),
        "source_sha": assessment.get("source_commit"),
        "arm_count": arm_count,
        **totals,
        "protected_counters": protected,
        "skew_observation_count": len(fair_positions),
        "fair_secondary_receipt_positions": sorted(set(fair_positions)),
        "legacy_secondary_receipt_positions": sorted(set(legacy_positions)),
        "self_scaling_floor": assessment.get("self_scaling_floor"),
        "self_scaling": normalized_scaling,
        "passed_scaling_workloads": sum(item["status"] == "VERIFIED" for item in scaling),
        "diagnostic_signals": diagnostic_signals,
    }


def ratio_or_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardEvidenceError("scheduler assessment value is not numeric")
    return float(value)


def _numeric(values: Mapping[str, Any], name: str) -> float:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardEvidenceError(f"scheduler grouped metric is not numeric: {name}")
    return float(value)


def _positive_ratio(
    numerator: Mapping[str, Any], denominator: Mapping[str, Any], name: str
) -> float:
    left = _numeric(denominator, name)
    right = _numeric(numerator, name)
    if left <= 0:
        raise ScorecardEvidenceError(f"scheduler grouped metric is not positive: {name}")
    return right / left


def _integer(row: Mapping[str, str], name: str) -> int:
    value = row.get(name)
    if value is None or re.fullmatch(r"-?[0-9]+", value) is None:
        raise ScorecardEvidenceError(f"scheduler CSV field is not an integer: {name}={value!r}")
    return int(value)


def _final_pair_metrics() -> dict[str, Any]:
    result = _object(FINAL_PAIR_PATH)
    expected = {
        "result": "FINAL_PAIR_CONTRACT_VERIFIED",
        "case_count": 18,
        "source_event_count": 15,
        "converted_event_count": 15,
        "unmapped_event_count": 0,
        "dropped_event_count": 0,
        "formal_ab_executed": False,
        "human_review_status": "PENDING",
        "shadow_release_status": "INPUT_BLOCKED",
        "production_ready": False,
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise ScorecardEvidenceError(f"Final Pair evidence drift: {field}")
    recorded = result.get("result_manifest_sha256")
    computed = _canonical_digest(result, exclude="result_manifest_sha256")
    if recorded != computed:
        raise ScorecardEvidenceError("Final Pair result manifest self-digest drift")
    return {field: result[field] for field in expected} | {
        "rag_source_sha": result.get("rag_source_sha"),
        "evalops_source_sha": result.get("evalops_source_sha"),
        "dataset_hash": result.get("dataset_hash"),
        "harness_schema": result.get("harness_schema"),
    }


def build_scorecard() -> dict[str, Any]:
    verify_cross_repository_manifest()
    pair = _final_pair_metrics()
    scheduler = _scheduler_metrics()
    final_evidence = _object(FINAL_EVIDENCE_PATH)
    local_validation = final_evidence.get("local_validation")
    ci = final_evidence.get("ci")
    if not isinstance(local_validation, dict) or not isinstance(ci, dict):
        raise ScorecardEvidenceError("final evidence validation metadata is absent")
    if ci.get("status") != "completed" or ci.get("conclusion") != "success":
        raise ScorecardEvidenceError("bound EvalOps CI is not successful")
    scorecard_source_sha = final_evidence.get("reviewed_source_sha")
    if (
        not isinstance(scorecard_source_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", scorecard_source_sha) is None
        or ci.get("head_sha") != scorecard_source_sha
    ):
        raise ScorecardEvidenceError("Scorecard source SHA and exact CI head do not match")
    evaluators = [descriptor.kind for descriptor in registered_agent_evaluators()]
    if len(evaluators) != 7:
        raise ScorecardEvidenceError("expected exactly seven built-in Agent evaluators")
    metric_catalog = (
        "job_queue_depth",
        "job_lease_expired_total",
        "worker_heartbeat_age",
        "db_operation_duration_seconds",
        "outbox_oldest_pending_age_seconds",
        "mcp_audit_oldest_pending_age_seconds",
        "mcp_audit_delivery_failures_total",
        "mcp_audit_dead_letter_count",
        "mcp_audit_delivery_latency_seconds",
    )
    rendered_metrics = PlatformMetrics().render().decode("utf-8")
    missing_metrics = [name for name in metric_catalog if name not in rendered_metrics]
    if missing_metrics:
        raise ScorecardEvidenceError(f"operational metric catalog drift: {missing_metrics}")

    scorecard: dict[str, Any] = {
        "schema_version": "ai-evalops-project-scorecard/v1",
        "scoring_policy": {
            "weighted_total": None,
            "reason": (
                "Mechanism, formal-quality, scalability, and production evidence are "
                "non-substitutable gates."
            ),
            "positive_statuses": ["VERIFIED_CONTROLLED", "MECHANISM_VERIFIED"],
            "blocking_statuses": [
                "QUALITY_EVIDENCE_INSUFFICIENT",
                "NEGATIVE_SCALING",
                "EXTERNAL_VALIDATION_REQUIRED",
            ],
        },
        "source_evidence": {
            "rag_sha": pair["rag_source_sha"],
            "final_pair_evalops_sha": pair["evalops_source_sha"],
            "scorecard_source_sha": scorecard_source_sha,
            "scorecard_ci": ci.get("url"),
            "scheduler_source_sha": scheduler["source_sha"],
            "final_pair": FINAL_PAIR_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "scheduler_assessment": SCHEDULER_ASSESSMENT_PATH.relative_to(PROJECT_ROOT).as_posix(),
        },
        "categories": {
            "engineering_correctness": {
                "status": "VERIFIED_CONTROLLED",
                "metrics": {
                    "non_integration_tests_passed": local_validation.get(
                        "non_integration_tests_passed"
                    ),
                    "local_external_service_skips": local_validation.get("tests_skipped"),
                    "exact_sha_ci": "SUCCESS",
                    "scheduler_arms": scheduler["arm_count"],
                    "submitted_unique_terminal_jobs": [
                        scheduler["submitted_count"],
                        scheduler["unique_job_count"],
                        scheduler["terminal_count"],
                    ],
                    "protected_counter_sum": sum(scheduler["protected_counters"].values()),
                },
                "scope": "local regression plus controlled CI/PostgreSQL scheduler evidence",
            },
            "agent_rag_quality": {
                "status": "QUALITY_EVIDENCE_INSUFFICIENT",
                "metrics": {
                    "registered_deterministic_evaluators": evaluators,
                    "final_pair_cases": pair["case_count"],
                    "formal_ab_executed": pair["formal_ab_executed"],
                    "human_review_status": pair["human_review_status"],
                    "shadow_release_status": pair["shadow_release_status"],
                },
                "scope": "exact-SHA interoperability only; no answer-quality delta",
            },
            "performance_scalability": {
                "status": "NEGATIVE_SCALING",
                "metrics": {
                    "required_4_to_8_ratio": scheduler["self_scaling_floor"],
                    "passed_workloads": scheduler["passed_scaling_workloads"],
                    "total_workloads": len(scheduler["self_scaling"]),
                    "workloads": scheduler["self_scaling"],
                    "diagnostic_signals": scheduler["diagnostic_signals"],
                    "fair_secondary_position": scheduler["fair_secondary_receipt_positions"],
                    "legacy_secondary_position": scheduler["legacy_secondary_receipt_positions"],
                },
                "scope": "frozen q1000/sample100/batch1 controlled experiment",
                "hypothesis_status": {
                    "hot_row_contention": "ASSOCIATED_NOT_CAUSALLY_PROVEN",
                    "postgres_lock_pressure": "ASSOCIATED_NOT_CAUSALLY_PROVEN",
                    "worker_coordination_overhead": "UNRESOLVED",
                    "measurement_perturbation": "NOT_RULED_OUT",
                },
            },
            "reliability": {
                "status": "VERIFIED_CONTROLLED",
                "metrics": {
                    "protected_counters": scheduler["protected_counters"],
                    "source_events": pair["source_event_count"],
                    "converted_events": pair["converted_event_count"],
                    "dropped_events": pair["dropped_event_count"],
                    "unmapped_events": pair["unmapped_event_count"],
                    "operational_metric_catalog": list(metric_catalog),
                },
                "scope": "bounded fault/concurrency and Final Pair contract evidence",
            },
            "security": {
                "status": "EXTERNAL_VALIDATION_REQUIRED",
                "metrics": {
                    "permission_boundary_evaluator": "permission_boundary" in evaluators,
                    "cross_tenant_and_revocation_mechanism_tests": "PRESENT",
                    "independent_security_assessment": "NOT_RUN",
                    "production_role_isolation": "NOT_VERIFIED",
                },
                "scope": "mechanism tests, not penetration test or production certification",
            },
            "evidence_sufficiency": {
                "status": "QUALITY_EVIDENCE_INSUFFICIENT",
                "metrics": {
                    "contract_result": pair["result"],
                    "dataset_hash": pair["dataset_hash"],
                    "formal_ab_executed": pair["formal_ab_executed"],
                    "human_review_status": pair["human_review_status"],
                    "production_ready": pair["production_ready"],
                },
                "scope": "portfolio evidence is sufficient; formal quality/release evidence is not",
            },
        },
        "overall_decision": {
            "portfolio": "READY_WITH_EXPLICIT_LIMITS",
            "release": "NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED",
            "production": "NOT_VERIFIED",
        },
        "next_measurement_gates": [
            {
                "gate": "formal_agent_quality_ab",
                "status": "INPUT_REQUIRED",
                "minimum_common_cases": 100,
                "minimum_cases_per_category": 10,
                "required_outputs": [
                    "task_success_delta",
                    "citation_correctness_delta",
                    "tool_error_rate_delta",
                    "latency_p95_delta",
                    "cost_delta",
                    "paired_bootstrap_95pct_ci",
                ],
            },
            {
                "gate": "human_review",
                "status": "HUMAN_REVIEW_PENDING",
                "required_outputs": ["two_blinded_reviews", "agreement", "cohens_kappa"],
            },
            {
                "gate": "production_readiness",
                "status": "ENVIRONMENT_REQUIRED",
                "required_outputs": [
                    "capacity",
                    "queue_wait_p95_p99",
                    "end_to_end_p95_p99",
                    "recovery_time",
                    "audit_delivery_latency",
                    "tenant_isolation_assessment",
                ],
            },
        ],
    }
    scorecard["scorecard_sha256"] = _canonical_digest(scorecard)
    return scorecard


def verify_scorecard(scorecard: Mapping[str, Any]) -> None:
    expected = build_scorecard()
    if scorecard != expected:
        raise ScorecardEvidenceError("project scorecard differs from authoritative evidence")


def render_markdown(scorecard: Mapping[str, Any]) -> str:
    categories = cast(dict[str, dict[str, Any]], scorecard["categories"])
    lines = [
        "# AI EvalOps Platform — Evidence-backed Project Scorecard",
        "",
        "> This scorecard has no weighted total: mechanism, quality, scalability, and",
        "> production evidence are non-substitutable gates.",
        "",
        "| Category | Status | Scope |",
        "| --- | --- | --- |",
    ]
    for name, category in categories.items():
        lines.append(f"| `{name}` | `{category['status']}` | {category['scope']} |")
    decision = cast(dict[str, str], scorecard["overall_decision"])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Portfolio: `{decision['portfolio']}`.",
            f"- Release: `{decision['release']}`.",
            f"- Production: `{decision['production']}`.",
            "",
            "## Machine-readable details",
            "",
            "All metric values, exact source identities, workload ratios and next gates are in",
            "[`PROJECT_SCORECARD.json`](PROJECT_SCORECARD.json). Regenerate and verify with:",
            "",
            "```bash",
            "python -m scripts.project_scorecard --write",
            "python -m scripts.project_scorecard",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_scorecard(scorecard: Mapping[str, Any]) -> None:
    SCORECARD_PATH.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    SCORECARD_MARKDOWN_PATH.write_text(render_markdown(scorecard), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate scorecard files")
    args = parser.parse_args(argv)
    expected = build_scorecard()
    if args.write:
        write_scorecard(expected)
    if not SCORECARD_PATH.is_file() or not SCORECARD_MARKDOWN_PATH.is_file():
        raise SystemExit("project scorecard files are absent; run with --write")
    verify_scorecard(_object(SCORECARD_PATH))
    if SCORECARD_MARKDOWN_PATH.read_text(encoding="utf-8") != render_markdown(expected):
        raise SystemExit("project scorecard Markdown differs from authoritative evidence")
    print(
        json.dumps(
            {
                "result": "PROJECT_SCORECARD_VERIFIED",
                "scorecard_sha256": expected["scorecard_sha256"],
                "overall_decision": expected["overall_decision"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
