"""Executable, evidence-bound formal Agent quality and blinded-review contracts."""

from __future__ import annotations

import hashlib
import hmac
import math
import random
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.external_harness.harness_envelope import canonical_sha256
from app.external_harness.quality_gate import (
    EvidencePolicy,
    EvidenceSufficiency,
    FormalEvidenceDecision,
    assess_evidence_sufficiency,
    common_case_set,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FormalCaseMeasurement(_StrictModel):
    case_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20_000)
    task_success: float = Field(ge=0.0, le=1.0)
    citation_correctness: float = Field(ge=0.0, le=1.0)
    tool_error_rate: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    cost_usd: float = Field(ge=0.0)
    answer: str = Field(max_length=100_000)
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)


class FormalArmResult(_StrictModel):
    schema_version: Literal["formal-agent-quality-arm/1.0"]
    arm: Literal["baseline", "candidate"]
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[FormalCaseMeasurement] = Field(min_length=2)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> FormalArmResult:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("formal arm contains duplicate case_id")
        return self


class FormalQualityPolicy(_StrictModel):
    schema_version: Literal["formal-agent-quality-policy/1.0"]
    minimum_common_cases: int = Field(ge=100)
    minimum_cases_per_category: int = Field(ge=10)
    required_categories: tuple[str, ...] = Field(min_length=1)
    bootstrap_resamples: int = Field(ge=100)
    bootstrap_seed: int = Field(ge=0)
    task_success_ci_lower_min: float = Field(ge=-1.0, le=1.0)
    citation_correctness_ci_lower_min: float = Field(ge=-1.0, le=1.0)
    tool_error_rate_ci_upper_max: float = Field(ge=-1.0, le=1.0)
    latency_p95_relative_delta_max: float = Field(ge=0.0)
    cost_mean_relative_delta_max: float = Field(ge=0.0)
    require_exact_case_set: bool = True

    @model_validator(mode="after")
    def categories_are_unique(self) -> FormalQualityPolicy:
        if len(self.required_categories) != len(set(self.required_categories)):
            raise ValueError("required_categories must be unique")
        return self


@dataclass(frozen=True, slots=True)
class FormalMetricAssessment:
    baseline_value: float
    candidate_value: float
    delta: float
    confidence_lower: float
    confidence_upper: float
    relative_delta: float | None
    passed: bool
    rule: str

    def as_json(self) -> dict[str, JsonValue]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FormalQualityAssessment:
    status: Literal["PASS", "FAIL", "INSUFFICIENT_EVIDENCE"]
    sufficiency: EvidenceSufficiency
    metrics: dict[str, FormalMetricAssessment]
    decision: FormalEvidenceDecision

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": "formal-agent-quality-assessment/1.0",
            "status": self.status,
            "sufficiency": asdict(self.sufficiency),
            "metrics": {name: metric.as_json() for name, metric in self.metrics.items()},
            "decision": asdict(self.decision),
            "decision_outcome": self.decision.outcome,
        }


def assess_formal_quality(
    *,
    baseline: FormalArmResult,
    candidate: FormalArmResult,
    policy: FormalQualityPolicy,
    evalops_sha: str,
    trace_status: Literal["PASS", "FAIL"],
    failure_matrix_status: Literal["PASS", "FAIL"],
) -> FormalQualityAssessment:
    """Assess a source-bound paired A/B without hiding missing or drifting cases."""

    if baseline.arm != "baseline" or candidate.arm != "candidate":
        raise ValueError("formal quality inputs must use baseline and candidate arm labels")
    if baseline.dataset_sha256 != candidate.dataset_sha256:
        raise ValueError("baseline and candidate dataset SHA differ")
    if len(evalops_sha) != 40 or any(
        character not in "0123456789abcdef" for character in evalops_sha
    ):
        raise ValueError("evalops_sha must be an exact lowercase Git SHA")

    baseline_by_id = {case.case_id: case for case in baseline.cases}
    candidate_by_id = {case.case_id: case for case in candidate.cases}
    common = common_case_set(
        {case_id: case.task_success for case_id, case in baseline_by_id.items()},
        {case_id: case.task_success for case_id, case in candidate_by_id.items()},
    )
    for case_id in common.common_ids:
        left = baseline_by_id[case_id]
        right = candidate_by_id[case_id]
        if (left.prompt, left.category) != (right.prompt, right.category):
            raise ValueError(f"prompt/category drift for common case {case_id}")

    category_by_case = {
        case_id: baseline_by_id[case_id].category for case_id in common.common_ids
    }
    sufficiency = assess_evidence_sufficiency(
        {case_id: baseline_by_id[case_id].task_success for case_id in baseline_by_id},
        {case_id: candidate_by_id[case_id].task_success for case_id in candidate_by_id},
        category_by_case=category_by_case,
        policy=EvidencePolicy(
            minimum_common_cases=policy.minimum_common_cases,
            minimum_cases_per_category=policy.minimum_cases_per_category,
            required_categories=policy.required_categories,
        ),
    )
    exact_case_set = not common.left_only_ids and not common.right_only_ids
    common_baseline = [baseline_by_id[case_id] for case_id in common.common_ids]
    common_candidate = [candidate_by_id[case_id] for case_id in common.common_ids]

    metrics = _metric_assessments(
        baseline=common_baseline,
        candidate=common_candidate,
        policy=policy,
    )
    metrics_payload = {name: metric.as_json() for name, metric in metrics.items()}
    metrics_passed = all(metric.passed for metric in metrics.values())
    required_segments_passed = not policy.require_exact_case_set or exact_case_set
    automated_passed = (
        sufficiency.status == "SUFFICIENT" and required_segments_passed and metrics_passed
    )
    decision = FormalEvidenceDecision(
        dataset_hash=baseline.dataset_sha256,
        policy_hash=canonical_sha256(policy.model_dump(mode="json")),
        baseline_sha=baseline.source_sha,
        candidate_sha=candidate.source_sha,
        evalops_sha=evalops_sha,
        common_case_ids_hash=common.common_ids_sha256,
        common_case_count=len(common.common_ids),
        per_category_counts=sufficiency.category_counts,
        a_only_count=len(common.left_only_ids),
        b_only_count=len(common.right_only_ids),
        required_category_coverage=policy.required_categories,
        minimum_common_cases=policy.minimum_common_cases,
        minimum_per_category=policy.minimum_cases_per_category,
        bootstrap_method="paired-percentile-bootstrap",
        automated_metrics_digest=canonical_sha256(metrics_payload),
        automated_metrics_passed=automated_passed,
        human_review_status="PENDING",
        trace_status=trace_status,
        failure_matrix_status=failure_matrix_status,
        formal_ab_eligible=True,
        evidence_sufficiency=sufficiency.status,
        required_segments_passed=required_segments_passed,
        contract_verified=False,
    )
    if sufficiency.status == "INSUFFICIENT_EVIDENCE":
        status: Literal["PASS", "FAIL", "INSUFFICIENT_EVIDENCE"] = "INSUFFICIENT_EVIDENCE"
    else:
        status = "PASS" if automated_passed else "FAIL"
    return FormalQualityAssessment(
        status=status,
        sufficiency=sufficiency,
        metrics=metrics,
        decision=decision,
    )


def build_blinded_review_packet(
    *,
    baseline: FormalArmResult,
    candidate: FormalArmResult,
    blinding_key: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a reviewer-safe packet and a separately held source mapping."""

    if len(blinding_key) < 32:
        raise ValueError("blinding_key must contain at least 32 bytes")
    if baseline.dataset_sha256 != candidate.dataset_sha256:
        raise ValueError("baseline and candidate dataset SHA differ")
    baseline_by_id = {case.case_id: case for case in baseline.cases}
    candidate_by_id = {case.case_id: case for case in candidate.cases}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("blinded review requires an exact common case set")

    ranked = sorted(
        baseline_by_id,
        key=lambda case_id: hmac.new(
            blinding_key,
            f"{baseline.dataset_sha256}:{case_id}".encode(),
            hashlib.sha256,
        ).digest(),
    )
    baseline_as_a = set(ranked[: len(ranked) // 2])
    packet_cases: list[dict[str, Any]] = []
    case_mapping: list[dict[str, str]] = []
    for case_id in sorted(baseline_by_id):
        left = baseline_by_id[case_id]
        right = candidate_by_id[case_id]
        if (left.prompt, left.category) != (right.prompt, right.category):
            raise ValueError(f"prompt/category drift for common case {case_id}")
        a_arm, b_arm = ((left, right) if case_id in baseline_as_a else (right, left))
        packet_cases.append(
            {
                "case_id": case_id,
                "category": left.category,
                "prompt": left.prompt,
                "answers": {
                    "A": {"answer": a_arm.answer, "citations": a_arm.citations},
                    "B": {"answer": b_arm.answer, "citations": b_arm.citations},
                },
            }
        )
        case_mapping.append(
            {
                "case_id": case_id,
                "A": "baseline" if case_id in baseline_as_a else "candidate",
                "B": "candidate" if case_id in baseline_as_a else "baseline",
            }
        )

    mapping_digest = canonical_sha256(case_mapping)
    packet_core = {
        "schema_version": "formal-agent-human-review-packet/1.0",
        "dataset_sha256": baseline.dataset_sha256,
        "mapping_sha256": mapping_digest,
        "cases": packet_cases,
    }
    packet_sha256 = canonical_sha256(packet_core)
    packet = {
        **packet_core,
        "packet_id": f"formal-review-{packet_sha256[:16]}",
        "packet_sha256": packet_sha256,
    }
    mapping = {
        "schema_version": "formal-agent-human-review-map/1.0",
        "packet_id": packet["packet_id"],
        "packet_sha256": packet_sha256,
        "mapping_sha256": mapping_digest,
        "baseline_sha": baseline.source_sha,
        "candidate_sha": candidate.source_sha,
        "case_mapping": case_mapping,
    }
    return packet, mapping


def _metric_assessments(
    *,
    baseline: list[FormalCaseMeasurement],
    candidate: list[FormalCaseMeasurement],
    policy: FormalQualityPolicy,
) -> dict[str, FormalMetricAssessment]:
    if len(baseline) < 2:
        raise ValueError("formal metric assessment requires at least two common cases")

    def values(field: str) -> tuple[list[float], list[float]]:
        return (
            [float(getattr(case, field)) for case in baseline],
            [float(getattr(case, field)) for case in candidate],
        )

    task = _bootstrap_metric(*values("task_success"), policy=policy, statistic="mean")
    citation = _bootstrap_metric(
        *values("citation_correctness"), policy=policy, statistic="mean"
    )
    tool_error = _bootstrap_metric(*values("tool_error_rate"), policy=policy, statistic="mean")
    latency = _bootstrap_metric(*values("latency_ms"), policy=policy, statistic="p95")
    cost = _bootstrap_metric(*values("cost_usd"), policy=policy, statistic="mean")
    return {
        "task_success_delta": _with_rule(
            task,
            passed=task.confidence_lower >= policy.task_success_ci_lower_min,
            rule=f"confidence_lower >= {policy.task_success_ci_lower_min}",
        ),
        "citation_correctness_delta": _with_rule(
            citation,
            passed=(
                citation.confidence_lower >= policy.citation_correctness_ci_lower_min
            ),
            rule=f"confidence_lower >= {policy.citation_correctness_ci_lower_min}",
        ),
        "tool_error_rate_delta": _with_rule(
            tool_error,
            passed=tool_error.confidence_upper <= policy.tool_error_rate_ci_upper_max,
            rule=f"confidence_upper <= {policy.tool_error_rate_ci_upper_max}",
        ),
        "latency_p95_delta": _with_rule(
            latency,
            passed=(
                latency.relative_delta is not None
                and latency.relative_delta <= policy.latency_p95_relative_delta_max
            ),
            rule=f"relative_delta <= {policy.latency_p95_relative_delta_max}",
        ),
        "cost_delta": _with_rule(
            cost,
            passed=(
                cost.relative_delta is not None
                and cost.relative_delta <= policy.cost_mean_relative_delta_max
            ),
            rule=f"relative_delta <= {policy.cost_mean_relative_delta_max}",
        ),
    }


def _bootstrap_metric(
    baseline: list[float],
    candidate: list[float],
    *,
    policy: FormalQualityPolicy,
    statistic: Literal["mean", "p95"],
) -> FormalMetricAssessment:
    if len(baseline) != len(candidate) or len(baseline) < 2:
        raise ValueError("paired metric inputs must contain the same cases")
    function = _mean if statistic == "mean" else _p95
    baseline_value = function(baseline)
    candidate_value = function(candidate)
    rng = random.Random(policy.bootstrap_seed)
    count = len(baseline)
    draws: list[float] = []
    for _ in range(policy.bootstrap_resamples):
        indexes = [rng.randrange(count) for _ in range(count)]
        left = [baseline[index] for index in indexes]
        right = [candidate[index] for index in indexes]
        draws.append(function(right) - function(left))
    draws.sort()
    delta = candidate_value - baseline_value
    relative_delta = _relative_delta(candidate_value, baseline_value)
    return FormalMetricAssessment(
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
        confidence_lower=_quantile(draws, 0.025),
        confidence_upper=_quantile(draws, 0.975),
        relative_delta=relative_delta,
        passed=False,
        rule="unassigned",
    )


def _with_rule(
    metric: FormalMetricAssessment, *, passed: bool, rule: str
) -> FormalMetricAssessment:
    return FormalMetricAssessment(
        baseline_value=metric.baseline_value,
        candidate_value=metric.candidate_value,
        delta=metric.delta,
        confidence_lower=metric.confidence_lower,
        confidence_upper=metric.confidence_upper,
        relative_delta=metric.relative_delta,
        passed=passed,
        rule=rule,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _p95(values: list[float]) -> float:
    return _quantile(sorted(values), 0.95)


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _relative_delta(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (candidate - baseline) / baseline


__all__ = [
    "FormalArmResult",
    "FormalCaseMeasurement",
    "FormalMetricAssessment",
    "FormalQualityAssessment",
    "FormalQualityPolicy",
    "assess_formal_quality",
    "build_blinded_review_packet",
]
