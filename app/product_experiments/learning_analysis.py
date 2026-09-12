"""Per-case explanations, blind-review input, and non-destructive regression focus."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from typing import Any

from app.product_experiments.evaluators import registered_evaluators
from app.product_experiments.learning_grading import grade_answer, make_review_packet
from app.product_experiments.learning_workflow import WorkflowEvidence, source_digest
from app.product_experiments.runner import ExperimentCase, ProviderResult, score_product_case
from app.product_experiments.trace_diagnostics import TraceBundle, summarize_trace


def build_analysis(
    evidence: WorkflowEvidence,
    *,
    profile: str = "normalized_exact_v1",
    traces: TraceBundle | None = None,
) -> dict[str, Any]:
    grade_answer("profile validation", "profile validation", profile=profile)
    result = evidence.result
    names = (
        ("reference_answer", "citation_correctness", "tool_error_rate")
        if result.task_type == "QA"
        else (
            "agent_task_completion",
            "tool_selection_accuracy",
            "tool_argument_validity",
            "policy_violation_rate",
            "tool_budget_violation_rate",
            "tool_error_rate",
        )
    )
    trace_counts = Counter(
        observation.trace_id.lower()
        for arm in result.observations.values()
        for observation in arm.values()
        if observation.trace_id is not None
    )
    rows: list[dict[str, Any]] = []
    observed = 0
    for case in evidence.cases:
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "category": case.category,
            "prompt": case.prompt,
            "reference_answer": case.reference_answer,
        }
        for arm in ("baseline", "candidate"):
            observation = result.observations.get(arm, {}).get(case.case_id)
            errors = [
                failure.error_code
                for failure in result.execution_errors
                if failure.case_id == case.case_id and failure.arm == arm
            ]
            if observation is None:
                row[arm] = {
                    "status": "MISSING_OBSERVATION",
                    "answer": None,
                    "grade": None,
                    "metrics": {},
                    "findings": errors or ["OBSERVATION_NOT_AVAILABLE"],
                    "trace": {"evidence_status": "NO_OBSERVATION"},
                }
                continue
            observed += 1
            grade = grade_answer(case.reference_answer, observation.answer, profile=profile)
            metrics = (
                {}
                if result.task_type == "AGENT_TOOL_USE" and observation.missing_fields
                else score_product_case(case, observation, evaluators=registered_evaluators(names))
            )
            findings = _findings(case, observation, metrics)
            if result.task_type == "AGENT_TOOL_USE" and observation.missing_fields:
                findings.append("MISSING_AGENT_OBSERVATION")
            if grade.grading_status != "INVALID_REFERENCE" and not grade.passed:
                findings.append("DIAGNOSTIC_ANSWER_MISMATCH")
            trace: dict[str, Any] = {"evidence_status": "NOT_SUPPLIED"}
            if traces is not None:
                trace_id = observation.trace_id
                if trace_id is None:
                    trace = {"evidence_status": "TRACE_ID_NOT_REPORTED"}
                elif not re.fullmatch(r"[0-9a-fA-F]{32}", trace_id) or int(trace_id, 16) == 0:
                    trace = {"evidence_status": "INVALID_TRACE_ID"}
                elif trace_counts[trace_id.lower()] > 1:
                    trace = {"evidence_status": "AMBIGUOUS_TRACE_BINDING"}
                else:
                    trace = summarize_trace(traces, trace_id.lower())
            row[arm] = {
                "status": "OBSERVED",
                "answer": observation.answer,
                "grade": grade.model_dump(mode="json"),
                "grader_input_problem": grade.grading_status == "INVALID_REFERENCE",
                "metrics": metrics,
                "findings": findings,
                "trace": trace,
                "cost_usd": observation.cost_usd,
                "latency_ms": observation.latency_ms,
                "cost_scope": "REPORTED_ACCEPTED_OBSERVATION_ONLY",
            }
        row["new_candidate_finding"] = (
            bool(row["candidate"]["findings"]) and not bool(row["baseline"]["findings"])
            if row["baseline"]["status"] == row["candidate"]["status"] == "OBSERVED"
            else None
        )
        rows.append(row)
    return {
        "schema_version": "evalops.learning-analysis/1.0",
        "decision_scope": "DIAGNOSTIC_ONLY",
        "source_sha256": source_digest(evidence),
        "verification_scope": evidence.verification_scope,
        "dataset_sha256": result.dataset_sha256,
        "evalops_sha": result.evalops_sha,
        "original_quality_status": result.status,
        "profile": profile,
        "case_count": len(rows),
        "planned_arm_count": len(rows) * 2,
        "observed_arm_count": observed,
        "missing_arm_count": len(rows) * 2 - observed,
        "candidate_finding_case_count": sum(bool(row["candidate"]["findings"]) for row in rows),
        "human_review_status": "PENDING",
        "cases": rows,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
        "limitations": [
            "Diagnostic profiles do not replace the frozen release gate.",
            "A finding is an observed symptom, not a proven root cause.",
            "Exact and JSON equality do not establish semantic correctness.",
            "Trace structure is reported, may be incomplete, and cannot prove task success.",
            "Trace raw attributes are not retained; their source hash is not provenance.",
            "Counts are descriptive; no statistical or production-readiness claim.",
        ],
    }


def _findings(
    case: ExperimentCase,
    observation: ProviderResult,
    metrics: dict[str, float],
) -> list[str]:
    del case
    lower = {"policy_violation_rate", "tool_budget_violation_rate", "tool_error_rate"}
    findings = [
        f"METRIC:{name}"
        for name, score in sorted(metrics.items())
        if (score > 0 if name in lower else score < 1)
    ]
    if observation.cost_usd is None:
        findings.append("MISSING_COST_MEASUREMENT")
    if "agent_task_completion" in metrics and observation.missing_fields:
        findings.append("MISSING_AGENT_OBSERVATION")
    return findings


def review_packet_for_analysis(report: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "case_id": case["case_id"],
            "arm": arm,
            "prompt": case["prompt"],
            "reference_answer": case["reference_answer"],
            "answer": case[arm]["answer"],
            "profile": report["profile"],
        }
        for case in report["cases"]
        for arm in ("baseline", "candidate")
        if case[arm]["status"] == "OBSERVED"
    ]
    if not rows:
        return {"status": "NO_OBSERVATIONS", "items": [], "human_review_status": "PENDING"}
    return make_review_packet(rows).model_dump(mode="json")


def regression_focus(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the full source dataset so a selected subset cannot replace the denominator."""
    focus = [
        {
            "case_id": case["case_id"],
            "candidate_findings": case["candidate"]["findings"],
            "baseline_findings": case["baseline"]["findings"],
            "new_candidate_finding": case["new_candidate_finding"],
        }
        for case in report["cases"]
        if case["baseline"]["findings"] or case["candidate"]["findings"]
    ]
    return {
        "schema_version": "evalops.regression-focus/1.0",
        "decision_scope": "DIAGNOSTIC_ONLY",
        "source_sha256": report["source_sha256"],
        "dataset_sha256": report["dataset_sha256"],
        "selection_rule": "ANY_ARM_FINDING_V1",
        "focus_case_count": len(focus),
        "evaluation_case_count": report["case_count"],
        "gold_modified": False,
        "dataset_policy": "FULL_SOURCE_UNCHANGED",
        "focus": focus,
        "limitations": [
            "Focus selection is outcome-dependent, not an unbiased benchmark.",
            "Rerun the full source dataset; never report focus-only improvement.",
        ],
        "formal_quality_claim_allowed": False,
    }


def render_analysis_html(report: dict[str, Any]) -> str:
    def escaped(value: object) -> str:
        return html.escape(str(value), quote=True)

    rows = []
    for case in report["cases"]:
        cells = [case["case_id"], case["prompt"], case["reference_answer"]]
        for arm in ("baseline", "candidate"):
            values = case[arm]
            grade = values["grade"]
            cells.extend(
                [
                    values["answer"],
                    grade["reason"] if grade else values["status"],
                    ", ".join(values["findings"]) or "No configured check failed",
                    json.dumps(values["trace"], ensure_ascii=False, sort_keys=True),
                ]
            )
        rows.append("<tr>" + "".join(f"<td>{escaped(cell)}</td>" for cell in cells) + "</tr>")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EvalOps · 可解释评测</title><style>
body{font:15px/1.6 system-ui;margin:30px;background:#f4f6fa;color:#182235}
main{max-width:1400px;margin:auto}section{overflow:auto;background:white;padding:20px}
table{border-collapse:collapse;min-width:1200px;width:100%}td,th{border:1px solid #d5dce7;
padding:10px;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere;max-width:380px}
.boundary{padding:15px;background:#e9effc;border-left:4px solid #345ac7}
</style><main><h1>AI EvalOps · 从失败到回归</h1>
<p class="boundary">PRIVATE · 包含题目和答案，请勿公开。诊断分数不改变原门禁；
人工复核尚未完成；轨迹是报告的信息，不是根因证明。</p>""" + (
        f"<p>原状态：{escaped(report['original_quality_status'])} · "
        f"来源验证：{escaped(report['verification_scope'])} · "
        f"覆盖：{report['observed_arm_count']}/{report['planned_arm_count']} 个执行单元</p>"
        "<section><table><thead><tr><th>Case</th><th>输入</th><th>参考答案</th>"
        "<th>A 答案</th><th>A 判分理由</th><th>A 发现</th><th>A 轨迹</th>"
        "<th>B 答案</th><th>B 判分理由</th><th>B 发现</th><th>B 轨迹</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
        "<h2>下一步</h2><p>查看 findings 与 trace 的对应关系；填写盲审模板；"
        "修复后重跑完整 regression 数据集，重点检查 focus 中的题目。"
        "没有完整轨迹或人工标签时，保留未知，不自动归因。</p></main></html>"
    )
