"""Task-aware automated assessment, separate from formal evidence qualification."""

from dataclasses import asdict
from typing import Any, Literal

from app.external_harness.formal_quality import FormalQualityPolicy, assess_paired_numeric_metrics
from app.external_harness.quality_gate import EvidencePolicy, assess_evidence_sufficiency
from app.product_experiments.measurements import ProductArmResult


def assess_product_numeric(
    baseline: ProductArmResult,
    candidate: ProductArmResult,
    *,
    policy: FormalQualityPolicy,
    task_type: Literal["QA", "AGENT_TOOL_USE"],
    citation_precision_min: float = 0.95,
) -> dict[str, Any]:
    left = {case.case_id: case for case in baseline.cases}
    right = {case.case_id: case for case in candidate.cases}
    if set(left) != set(right):
        raise ValueError("product assessment requires the exact paired case set")
    for identity in left:
        if (left[identity].prompt, left[identity].category) != (
            right[identity].prompt,
            right[identity].category,
        ):
            raise ValueError("paired case inputs differ")
    sufficiency = assess_evidence_sufficiency(
        {key: value.task_success for key, value in left.items()},
        {key: value.task_success for key, value in right.items()},
        category_by_case={key: value.category for key, value in left.items()},
        policy=EvidencePolicy(
            minimum_common_cases=policy.minimum_common_cases,
            minimum_cases_per_category=policy.minimum_cases_per_category,
            required_categories=policy.required_categories,
        ),
    )
    names = ("task_success", "citation_correctness", "tool_error_rate", "latency_ms", "cost_usd")
    identities = sorted(left)
    metrics = assess_paired_numeric_metrics(
        baseline=[{name: getattr(left[key], name) for name in names} for key in identities],
        candidate=[{name: getattr(right[key], name) for name in names} for key in identities],
        policy=policy,
        include_citations=task_type == "QA",
    )
    metric_payload = {name: value.as_json() for name, value in metrics.items()}
    precision_passed = True
    if task_type == "QA":
        metric_payload["citation_recall_delta"] = metric_payload.pop("citation_correctness_delta")
        precisions = [case.citation_precision for case in candidate.cases]
        complete = all(value is not None for value in precisions)
        mean_precision = (
            sum(value for value in precisions if value is not None) / len(precisions)
            if complete
            else None
        )
        precision_passed = mean_precision is not None and mean_precision >= citation_precision_min
        metric_payload["citation_precision"] = {
            "candidate_value": mean_precision,
            "passed": precision_passed,
            "rule": f"candidate_mean >= {citation_precision_min}",
            "method": "descriptive source-ID precision; not semantic citation support",
        }
    return {
        "schema_version": "evalops.product-automated-assessment/2.0",
        "status": (
            "INSUFFICIENT_EVIDENCE"
            if sufficiency.status != "SUFFICIENT"
            else "PASS"
            if all(metric.passed for metric in metrics.values()) and precision_passed
            else "FAIL"
        ),
        "sufficiency": asdict(sufficiency),
        "metrics": metric_payload,
        "metric_applicability": {
            "citation": "APPLICABLE" if task_type == "QA" else "NOT_APPLICABLE"
        },
        "decision": {
            "formal_ab_eligible": False,
            "trace_status": "NOT_VERIFIED",
            "failure_matrix_status": "NOT_RUN",
        },
        "decision_outcome": "INPUT_BLOCKED",
    }
