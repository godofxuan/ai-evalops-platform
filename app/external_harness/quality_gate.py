"""Paired evidence statistics and fail-closed shadow release decisions."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Literal

GateStatus = Literal["PASS", "FAIL", "HUMAN_REVIEW_PENDING", "INPUT_BLOCKED"]
AutomatedStatus = Literal["PASS", "FAIL", "INPUT_BLOCKED"]


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


@dataclass(frozen=True, slots=True)
class ShadowGateInputs:
    automated_status: AutomatedStatus
    human_review_complete: bool
    trace_correlation_passed: bool
    failure_matrix_passed: bool


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
) -> BootstrapInterval:
    """Estimate candidate-minus-baseline delta only over the frozen intersection."""

    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    common = common_case_set(left, right)
    if not common.common_ids:
        raise ValueError("paired bootstrap requires at least one common case")
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
    )


def evaluate_shadow_gate(inputs: ShadowGateInputs) -> ShadowGateDecision:
    hard_failures = tuple(
        reason
        for condition, reason in (
            (not inputs.trace_correlation_passed, "trace_correlation_failed"),
            (not inputs.failure_matrix_passed, "failure_matrix_failed"),
            (inputs.automated_status == "FAIL", "automated_quality_failed"),
        )
        if condition
    )
    if hard_failures:
        return ShadowGateDecision("FAIL", hard_failures)
    if inputs.automated_status == "INPUT_BLOCKED":
        return ShadowGateDecision("INPUT_BLOCKED", ("automated_comparison_input_missing",))
    if not inputs.human_review_complete:
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
    "ShadowGateDecision",
    "ShadowGateInputs",
    "common_case_set",
    "evaluate_shadow_gate",
    "paired_bootstrap_delta",
]
