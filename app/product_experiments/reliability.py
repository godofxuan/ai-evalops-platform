"""Descriptive, plan-bound repeat panels over privately recomputed durable pairs.

A trial is a whole execution under a fixed retry policy, not an attempt, model
sample, quality gate or proof of statistical independence/server provenance.
"""

import hashlib
import html
import json
import math
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.strict_json import decode_evidence_json
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.runner import ExperimentCase, parse_product_dataset
from app.product_experiments.submission import DurableExperimentRequest
from app.runs.idempotency import canonical_request_hash

MAX_PANEL_CELLS = 20_000  # Per arm; never treat these as independent cases.
MAX_PANEL_REPORT_BYTES = 32 * 1024 * 1024


class ReliabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schema_version: Literal["evalops.reliability-plan/1.0"] = "evalops.reliability-plan/1.0"
    panel_id: UUID
    tenant_id: UUID
    trial_count: int = Field(ge=2, le=10)
    request: DurableExperimentRequest
    evalops_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    environment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampling_kind: Literal["SYNTHETIC", "TARGET_DECLARED"]

    @model_validator(mode="after")
    def bounded_attempts(self) -> "ReliabilityPlan":
        if self.trial_count * self.request.max_total_attempts > 200_000:
            raise ValueError("panel_attempt_limit")
        return self

    @property
    def plan_sha256(self) -> str:
        return canonical_request_hash(self.model_dump(mode="json"))

    def idempotency_key(self, trial: int) -> str:
        if type(trial) is not int or not 1 <= trial <= self.trial_count:
            raise ValueError("invalid_trial_index")
        return f"rel-{self.plan_sha256}-t{trial:02d}"

    def trial_request(self, trial: int) -> DurableExperimentRequest:
        values = self.request.model_dump(mode="json")
        values["experiment_id"] = self.idempotency_key(trial)
        return DurableExperimentRequest.model_validate_json(json.dumps(values, allow_nan=False))

    def validate_dataset(self, raw_dataset: bytes) -> tuple[ExperimentCase, ...]:
        if not 0 < len(raw_dataset) <= 10 * 1024 * 1024:
            raise ValueError("invalid_panel_dataset_size")
        cases = tuple(
            parse_product_dataset(raw_dataset, expected_sha256=self.request.source_dataset_sha256)
        )
        if len(cases) * self.trial_count > MAX_PANEL_CELLS:
            raise ValueError("panel_case_limit")
        if len(cases) * self.request.policy.bootstrap_resamples > 2_000_000:
            raise ValueError("panel_bootstrap_limit")
        if self.request.max_observation_bytes < 2 * len(cases):
            raise ValueError("panel_observation_budget_cannot_cover_cases")
        if len(cases) * 2 * self.request.max_attempts > self.request.max_total_attempts:
            raise ValueError("panel_attempt_budget_cannot_cover_cases")
        return cases


def _measurement(row: dict[str, Any], *, task_type: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "UNKNOWN",
        "success": None,
        "attempt_count": row["attempt_count"],
        "accepted_attempt_number": row["accepted_attempt_number"],
        "latency_ms": None,
        "cost_usd": None,
        "guardrail_metrics": {},
    }
    if row["job_status"] in {"failed", "cancelled"}:
        result["status"] = "EXECUTION_FAILED" if row["job_status"] == "failed" else "CANCELLED"
        return result
    metrics = row["metrics"]
    observation = metrics["product_observation"]
    for field in ("latency_ms", "cost_usd"):
        value = observation.get(field)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("panel_invalid_measurement")
            result[field] = value
    if metrics["product_status"] != "OBSERVED":
        return result
    scores = metrics["product_scores"]
    score = scores["reference_answer" if task_type == "QA" else "agent_task_completion"]
    if type(score) not in (int, float) or score not in (0.0, 1.0):
        raise ValueError("panel_requires_binary_success")
    result.update(status="OBSERVED", success=score == 1.0)
    result["guardrail_metrics"] = {
        name: scores[name]
        for name in ("tool_error_rate", "policy_violation_rate", "tool_budget_violation_rate")
        if name in scores
    }
    return result


def _summary(rows: list[dict[str, Any]], case_ids: list[str], k: int) -> dict[str, Any]:
    counts = {
        state: sum(row["status"] == state for row in rows)
        for state in ("OBSERVED", "MISSING_TRIAL", "EXECUTION_FAILED", "CANCELLED", "UNKNOWN")
    }
    complete = counts["OBSERVED"] == len(rows)
    observed = [row for row in rows if row["status"] == "OBSERVED"]
    cells_by_case: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    for row in rows:
        cells_by_case[row["case_id"]].append(row)
    per_case = []
    histogram = {str(number): 0 for number in range(k + 1)}
    for case_id in case_ids:
        cells = cells_by_case[case_id]
        successes = sum(row["success"] is True for row in cells)
        is_complete = all(row["status"] == "OBSERVED" for row in cells)
        if is_complete:
            histogram[str(successes)] += 1
        per_case.append(
            {
                "case_id": case_id,
                "successes": successes,
                "observed": sum(row["status"] == "OBSERVED" for row in cells),
                "expected": k,
                "complete": is_complete,
            }
        )
    latencies = sorted(row["latency_ms"] for row in rows if row["latency_ms"] is not None)
    costs = [row["cost_usd"] for row in rows if row["cost_usd"] is not None]
    total_cost = sum(costs) if costs else None
    if total_cost is not None and not math.isfinite(total_cost):
        raise ValueError("panel_measurement_overflow")
    guardrails = {}
    for name in ("tool_error_rate", "policy_violation_rate", "tool_budget_violation_rate"):
        values = [
            row["guardrail_metrics"][name] for row in rows if name in row["guardrail_metrics"]
        ]
        guardrails[name] = {
            "observed": len(values),
            "expected": len(rows),
            "observed_mean": sum(values) / len(values) if values else None,
        }
    return {
        "status": "COMPLETE_DESCRIPTIVE_PANEL" if complete else "INSUFFICIENT_EVIDENCE",
        "expected_cells": len(rows),
        "counts": counts,
        "coverage": len(observed) / len(rows),
        "observed_success_rate": sum(row["success"] is True for row in observed) / len(observed)
        if observed
        else None,
        "mean_task_success": sum(row["success"] is True for row in rows) / len(rows)
        if complete
        else None,
        "empirical_any_at_k": sum(row["successes"] > 0 for row in per_case) / len(case_ids)
        if complete
        else None,
        "empirical_all_at_k": sum(row["successes"] == k for row in per_case) / len(case_ids)
        if complete
        else None,
        "complete_case_success_count_histogram": histogram,
        "per_case": per_case,
        "accepted_observation_cost_usd": total_cost,
        "cost_observed_cells": len(costs),
        "total_execution_cost_usd": None,
        "accepted_observation_latency_p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1]
        if latencies
        else None,
        "latency_observed_cells": len(latencies),
        "known_attempts": sum(row["attempt_count"] or 0 for row in rows),
        "known_retries": sum(max(0, (row["attempt_count"] or 0) - 1) for row in rows),
        "guardrail_metrics": guardrails,
    }


def build_reliability_report(
    *, plan: ReliabilityPlan, raw_dataset: bytes, reports: Sequence[tuple[int, bytes]]
) -> dict[str, Any]:
    plan = ReliabilityPlan.model_validate_json(plan.model_dump_json())
    cases = plan.validate_dataset(raw_dataset)
    if len(reports) > plan.trial_count:
        raise ValueError("panel_too_many_reports")
    if sum(len(payload) for _, payload in reports) > 128 * 1024 * 1024:
        raise ValueError("panel_evidence_byte_limit")
    by_trial: dict[int, dict[str, Any]] = {}
    pins: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    components_hash: str | None = None

    def unique(kind: str, value: str) -> None:
        UUID(value)
        identity = (kind, value)
        if identity in seen:
            raise ValueError("panel_reused_execution_identity")
        seen.add(identity)

    for trial, payload in sorted(reports, key=lambda item: item[0]):
        expected_request = plan.trial_request(trial)
        if trial in by_trial:
            raise ValueError("panel_duplicate_trial")
        verification = verify_durable_report(payload, raw_dataset=raw_dataset)
        if verification.verification_scope != "PRIVATE_RECOMPUTED":
            raise ValueError("panel_private_recomputation_required")
        report = decode_evidence_json(payload)
        snapshot = report["result_snapshot"]
        inputs = snapshot["input_snapshot"]
        if (
            snapshot["tenant_id"] != str(plan.tenant_id)
            or inputs["evalops_sha"] != plan.evalops_sha
            or canonical_request_hash(inputs["request"])
            != canonical_request_hash(expected_request.model_dump(mode="json"))
        ):
            raise ValueError("panel_plan_binding_mismatch")
        current_components = canonical_request_hash(inputs["components"])
        if components_hash is not None and components_hash != current_components:
            raise ValueError("panel_component_drift")
        components_hash = current_components
        unique("execution", snapshot["experiment_id"])
        for arm in snapshot["arms"].values():
            unique("run", arm["run_id"])
            for job in arm["jobs"]:
                unique("job", job["job_id"])
                if type(job["attempt_count"]) is not int or not (
                    0 <= job["attempt_count"] <= plan.request.max_attempts
                ):
                    raise ValueError("panel_invalid_attempt_count")
                for kind, key in (("result", "result_id"), ("attempt", "accepted_attempt_id")):
                    if job[key] is not None:
                        unique(kind, job[key])
        by_trial[trial] = snapshot
        pins.append(
            {
                "trial": trial,
                "experiment_id": snapshot["experiment_id"],
                "report_sha256": verification.report_sha256,
                "reported_quality_status": verification.quality_status,
            }
        )
    arms: dict[str, dict[str, Any]] = {}
    case_ids = [case.case_id for case in cases]
    for label in ("baseline", "candidate"):
        rows = []
        for trial in range(1, plan.trial_count + 1):
            jobs = (
                {row["case_id"]: row for row in by_trial[trial]["arms"][label]["jobs"]}
                if trial in by_trial
                else {}
            )
            for case_id in case_ids:
                cell = (
                    _measurement(jobs[case_id], task_type=plan.request.task_type)
                    if jobs
                    else {
                        "status": "MISSING_TRIAL",
                        "success": None,
                        "attempt_count": None,
                        "accepted_attempt_number": None,
                        "latency_ms": None,
                        "cost_usd": None,
                        "guardrail_metrics": {},
                    }
                )
                rows.append({"trial": trial, "case_id": case_id, **cell})
        arms[label] = {"summary": _summary(rows, case_ids, plan.trial_count), "cells": rows}
    complete = all(
        arm["summary"]["status"] == "COMPLETE_DESCRIPTIVE_PANEL" for arm in arms.values()
    )
    result: dict[str, Any] = {
        "schema_version": "evalops.reliability-report/1.0",
        "status": "COMPLETE_DESCRIPTIVE_PANEL" if complete else "INSUFFICIENT_EVIDENCE",
        "verification_scope": "PRIVATE_RECOMPUTED_PANEL",
        "visibility": "PRIVATE",
        "plan_sha256": plan.plan_sha256,
        "dataset_sha256": hashlib.sha256(raw_dataset).hexdigest(),
        "evalops_sha": plan.evalops_sha,
        "trial_count": plan.trial_count,
        "case_count": len(cases),
        "trial_unit": "DURABLE_PAIR_UNDER_FIXED_RETRY_POLICY",
        "max_attempts_per_job": plan.request.max_attempts,
        "sampling_kind": plan.sampling_kind,
        "statistical_independence": "NOT_ATTESTED",
        "preregistration": "CLIENT_PLAN_BOUND_ONLY",
        "server_provenance": "NOT_ATTESTED",
        "environment_attestation": "CLIENT_DECLARED_ONLY",
        "environment_sha256": plan.environment_sha256,
        "observed_components_sha256": components_hash,
        "component_attestation": "CONSISTENT_ACROSS_OBSERVED_TRIALS_NOT_PREREGISTERED",
        "success_definition": "QA_REFERENCE_ANSWER_OR_AGENT_TASK_COMPLETION_NOT_OVERALL_QUALITY",
        "cost_scope": "ACCEPTED_OBSERVATIONS_ONLY_EXCLUDES_UNACCEPTED_ATTEMPTS",
        "latency_scope": "ACCEPTED_OBSERVATIONS_NEAREST_RANK_P95_NOT_END_TO_END",
        "estimator": "FIXED_PANEL_EMPIRICAL_PROPORTIONS_NO_CONFIDENCE_INTERVAL",
        "trial_reports": pins,
        "arms": arms,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    result["content_sha256"] = canonical_request_hash(result)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PANEL_REPORT_BYTES:
        raise ValueError("panel_report_byte_limit")
    return result


def render_reliability_html(report: dict[str, Any]) -> str:
    """Private readable projection; never execute user-controlled HTML."""
    data = html.escape(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True)
    )
    table = ""
    for label in ("baseline", "candidate"):
        summary = report["arms"][label]["summary"]
        values = [
            label,
            summary["status"],
            summary["coverage"],
            summary["mean_task_success"],
            summary["empirical_any_at_k"],
            summary["empirical_all_at_k"],
            summary["known_retries"],
        ]
        table += (
            "<tr>"
            + "".join(
                "<td>" + html.escape(str(value) if value is not None else "证据不足") + "</td>"
                for value in values
            )
            + "</tr>"
        )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        "<title>EvalOps 重复运行可靠性报告</title>"
        "<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:32px auto;padding:16px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}</style>"
        "<h1>重复运行可靠性（私有描述性报告）</h1>"
        "<p>不是正式质量 PASS；不是模型独立采样证明。失败、取消和缺失不得丢弃。"
        "成本仅含已接受观测，不含失败重试；原文和金标不在本报告中，但案例标识仍属私有。</p>"
        "<table><thead><tr><th>组别</th><th>状态</th><th>覆盖率</th><th>平均任务成功率</th>"
        "<th>至少一次成功</th><th>全部成功</th><th>已知重试次数</th></tr></thead>"
        f"<tbody>{table}</tbody></table><details><summary>完整私有证据与逐题结果</summary>"
        f'<pre style="white-space:pre-wrap;overflow-wrap:anywhere">{data}</pre></details></html>'
    )


def verify_reliability_report(
    payload: bytes,
    *,
    plan: ReliabilityPlan,
    raw_dataset: bytes,
    reports: Sequence[tuple[int, bytes]],
) -> None:
    if not 0 < len(payload) <= MAX_PANEL_REPORT_BYTES:
        raise ValueError("panel_report_byte_limit")
    actual = decode_evidence_json(payload)
    rebuilt = build_reliability_report(plan=plan, raw_dataset=raw_dataset, reports=reports)
    if canonical_request_hash(actual) != canonical_request_hash(rebuilt):
        raise ValueError("panel_report_recomputation_mismatch")
