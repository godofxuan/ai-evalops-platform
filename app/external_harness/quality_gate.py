"""Paired evidence statistics and fail-closed shadow release decisions."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass
from typing import Literal

GateStatus = Literal[
    "PASS", "FAIL", "HUMAN_REVIEW_PENDING", "INPUT_BLOCKED", "INSUFFICIENT_EVIDENCE"
]
AutomatedStatus = Literal["PASS", "FAIL", "INPUT_BLOCKED", "INSUFFICIENT_EVIDENCE"]
EvidenceOutcome = Literal[
    "PASS", "FAIL", "INPUT_BLOCKED", "INSUFFICIENT_EVIDENCE", "CONTRACT_VERIFIED"
]


class InsufficientEvidenceError(ValueError):
    """A statistical estimate was requested without enough paired evidence."""


@dataclass(frozen=True, slots=True)
class CommonCaseSet:
    common_ids: tuple[str, ...]
    left_only_ids: tuple[str, ...]
    right_only_ids: tuple[str, ...]
    common_ids_sha256: str


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    sample_count: int
    mean_delta: float
    confidence_level: float
    lower: float
    upper: float
    resamples: int
    seed: int
    common_case_ids_sha256: str
    method: Literal["paired-percentile-bootstrap"]


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    minimum_common_cases: int = 100
    minimum_cases_per_category: int = 10
    required_categories: tuple[str, ...] = ()


DEFAULT_EVIDENCE_POLICY = EvidencePolicy()


@dataclass(frozen=True, slots=True)
class EvidenceSufficiency:
    status: Literal["SUFFICIENT", "INSUFFICIENT_EVIDENCE"]
    common_case_count: int
    category_counts: dict[str, int]
    left_only_ids: tuple[str, ...]
    right_only_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FormalEvidenceDecision:
    dataset_hash: str
    policy_hash: str
    baseline_sha: str
    candidate_sha: str
    evalops_sha: str
    common_case_ids_hash: str
    common_case_count: int
    per_category_counts: dict[str, int]
    a_only_count: int
    b_only_count: int
    required_category_coverage: tuple[str, ...]
    minimum_common_cases: int
    minimum_per_category: int
    bootstrap_method: Literal["paired-percentile-bootstrap"]
    automated_metrics_digest: str
    automated_metrics_passed: bool
    human_review_status: Literal["PENDING", "COMPLETE"]
    trace_status: Literal["PASS", "FAIL"]
    failure_matrix_status: Literal["PASS", "FAIL"]
    formal_ab_eligible: bool
    evidence_sufficiency: Literal["SUFFICIENT", "INSUFFICIENT_EVIDENCE"]
    required_segments_passed: bool = True
    contract_verified: bool = False

    def __post_init__(self) -> None:
        for name in (
            "dataset_hash",
            "policy_hash",
            "common_case_ids_hash",
            "automated_metrics_digest",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        for name in ("baseline_sha", "candidate_sha", "evalops_sha"):
            if re.fullmatch(r"[0-9a-f]{40}", getattr(self, name)) is None:
                raise ValueError(f"{name} must be an exact lowercase Git SHA")
        counts = (self.common_case_count, self.a_only_count, self.b_only_count)
        if any(count < 0 for count in counts) or any(
            count < 0 for count in self.per_category_counts.values()
        ):
            raise ValueError("evidence counts must be nonnegative")
        if self.minimum_common_cases < 2 or self.minimum_per_category < 1:
            raise ValueError("formal evidence minimums are invalid")
        if self.formal_ab_eligible and self.contract_verified:
            raise ValueError("formal A/B evidence cannot also be a contract-only result")

    @property
    def outcome(self) -> EvidenceOutcome:
        if not self.formal_ab_eligible:
            return "CONTRACT_VERIFIED" if self.contract_verified else "INPUT_BLOCKED"
        if self.evidence_sufficiency == "INSUFFICIENT_EVIDENCE":
            return "INSUFFICIENT_EVIDENCE"
        if self.common_case_count < self.minimum_common_cases or any(
            self.per_category_counts.get(category, 0) < self.minimum_per_category
            for category in self.required_category_coverage
        ):
            return "INSUFFICIENT_EVIDENCE"
        return "PASS" if self.automated_metrics_passed else "FAIL"


@dataclass(frozen=True, slots=True)
class ShadowGateDecision:
    status: GateStatus
    reasons: tuple[str, ...]


def common_case_set(left: dict[str, float], right: dict[str, float]) -> CommonCaseSet:
    common = tuple(sorted(set(left) & set(right)))
    encoded = json.dumps(common, separators=(",", ":"), ensure_ascii=False).encode()
    return CommonCaseSet(
        common_ids=common,
        left_only_ids=tuple(sorted(set(left) - set(right))),
        right_only_ids=tuple(sorted(set(right) - set(left))),
        common_ids_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def paired_bootstrap_delta(
    left: dict[str, float],
    right: dict[str, float],
    *,
    resamples: int = 10_000,
    seed: int = 20_260_821,
    confidence_level: float = 0.95,
    minimum_common_cases: int = 2,
) -> BootstrapInterval:
    """Estimate candidate-minus-baseline delta only over the frozen intersection."""

    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    if minimum_common_cases < 2:
        raise ValueError("minimum_common_cases must be at least two")
    common = common_case_set(left, right)
    if len(common.common_ids) < minimum_common_cases:
        raise InsufficientEvidenceError(
            f"paired bootstrap requires at least {minimum_common_cases} common cases"
        )
    deltas = [
        _finite(right[case_id], f"right[{case_id}]") - _finite(left[case_id], f"left[{case_id}]")
        for case_id in common.common_ids
    ]
    rng = random.Random(seed)
    count = len(deltas)
    draws = sorted(
        sum(deltas[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples)
    )
    alpha = (1.0 - confidence_level) / 2.0
    return BootstrapInterval(
        sample_count=count,
        mean_delta=sum(deltas) / count,
        confidence_level=confidence_level,
        lower=_quantile(draws, alpha),
        upper=_quantile(draws, 1.0 - alpha),
        resamples=resamples,
        seed=seed,
        common_case_ids_sha256=common.common_ids_sha256,
        method="paired-percentile-bootstrap",
    )


def assess_evidence_sufficiency(
    left: dict[str, float],
    right: dict[str, float],
    *,
    category_by_case: dict[str, str],
    policy: EvidencePolicy = DEFAULT_EVIDENCE_POLICY,
) -> EvidenceSufficiency:
    common = common_case_set(left, right)
    counts = {
        category: sum(category_by_case.get(case_id) == category for case_id in common.common_ids)
        for category in policy.required_categories
    }
    reasons: list[str] = []
    if len(common.common_ids) < policy.minimum_common_cases:
        reasons.append("minimum_common_cases_not_met")
    reasons.extend(
        f"category_under_minimum:{category}"
        for category, count in counts.items()
        if count < policy.minimum_cases_per_category
    )
    if any(case_id not in category_by_case for case_id in common.common_ids):
        reasons.append("required_category_mapping_missing")
    return EvidenceSufficiency(
        status="INSUFFICIENT_EVIDENCE" if reasons else "SUFFICIENT",
        common_case_count=len(common.common_ids),
        category_counts=counts,
        left_only_ids=common.left_only_ids,
        right_only_ids=common.right_only_ids,
        reasons=tuple(reasons),
    )


def evaluate_shadow_gate(inputs: FormalEvidenceDecision) -> ShadowGateDecision:
    hard_failures = tuple(
        reason
        for condition, reason in (
            (inputs.trace_status != "PASS", "trace_correlation_failed"),
            (inputs.failure_matrix_status != "PASS", "failure_matrix_failed"),
            (not inputs.required_segments_passed, "required_segment_failed"),
            (inputs.outcome == "FAIL", "automated_quality_failed"),
        )
        if condition
    )
    if hard_failures:
        return ShadowGateDecision("FAIL", hard_failures)
    if not inputs.formal_ab_eligible:
        reason = (
            "contract_verified_not_formal_ab"
            if inputs.contract_verified
            else "formal_ab_ineligible"
        )
        return ShadowGateDecision("INPUT_BLOCKED", (reason,))
    if inputs.outcome == "INPUT_BLOCKED":
        return ShadowGateDecision("INPUT_BLOCKED", ("automated_comparison_input_missing",))
    if inputs.outcome == "INSUFFICIENT_EVIDENCE":
        return ShadowGateDecision(
            "INSUFFICIENT_EVIDENCE",
            ("formal_sample_or_coverage_minimum_not_met",),
        )
    if inputs.human_review_status != "COMPLETE":
        return ShadowGateDecision("HUMAN_REVIEW_PENDING", ("real_human_review_incomplete",))
    return ShadowGateDecision("PASS", ())


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


__all__ = [
    "BootstrapInterval",
    "CommonCaseSet",
    "EvidencePolicy",
    "EvidenceSufficiency",
    "InsufficientEvidenceError",
    "ShadowGateDecision",
    "FormalEvidenceDecision",
    "assess_evidence_sufficiency",
    "common_case_set",
    "evaluate_shadow_gate",
    "paired_bootstrap_delta",
]
