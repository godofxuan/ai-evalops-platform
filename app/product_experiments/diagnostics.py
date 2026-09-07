"""Descriptive paired coverage, separate from release gates and statistical inference."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.product_experiments.evaluators import registered_evaluators

if TYPE_CHECKING:
    from app.product_experiments.runner import ExperimentCase, ProviderResult


class MetricDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    decision_scope: Literal["DESCRIPTIVE_ONLY"] = "DESCRIPTIVE_ONLY"
    direction: Literal["higher_is_better", "lower_is_better"]
    case_count: int = Field(ge=0)
    baseline_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    valid_pair_count: int = Field(ge=0)
    missing_pair_count: int = Field(ge=0)
    candidate_wins: int = Field(ge=0)
    candidate_losses: int = Field(ge=0)
    ties: int = Field(ge=0)
    mean_paired_delta: float | None

    @model_validator(mode="after")
    def consistent_counts(self) -> MetricDiagnostic:
        if (
            self.valid_pair_count + self.missing_pair_count != self.case_count
            or self.candidate_wins + self.candidate_losses + self.ties != self.valid_pair_count
            or not self.valid_pair_count <= self.baseline_count <= self.case_count
            or not self.valid_pair_count <= self.candidate_count <= self.case_count
        ):
            raise ValueError("diagnostic counts are inconsistent")
        return self


def build_metric_diagnostics(
    cases: list[ExperimentCase],
    observations: dict[str, dict[str, ProviderResult]],
    *,
    evaluator_names: tuple[str, ...],
) -> dict[str, MetricDiagnostic]:
    from app.product_experiments.runner import score_product_case

    evaluators = registered_evaluators(evaluator_names)
    names = (*evaluator_names, "latency_ms", "cost_usd")
    if "citation_correctness" in evaluator_names:
        names += ("citation_recall", "citation_precision")
    values: dict[str, dict[str, dict[str, float]]] = {
        name: {"baseline": {}, "candidate": {}} for name in names
    }
    for case in cases:
        for label in ("baseline", "candidate"):
            observation = observations.get(label, {}).get(case.case_id)
            if observation is None:
                continue
            measured: dict[str, float | None] = {
                "latency_ms": observation.latency_ms,
                "cost_usd": observation.cost_usd,
            }
            if "agent_task_completion" not in evaluator_names or not observation.missing_fields:
                measured.update(score_product_case(case, observation, evaluators=evaluators))
            for name in names:
                value = measured.get(name)
                if value is not None and math.isfinite(value):
                    values[name][label][case.case_id] = value
    result: dict[str, MetricDiagnostic] = {}
    lower = {
        "latency_ms",
        "cost_usd",
        "tool_error_rate",
        "policy_violation_rate",
        "tool_budget_violation_rate",
    }
    for name, arms in values.items():
        baseline, candidate = arms["baseline"], arms["candidate"]
        paired = sorted(set(baseline) & set(candidate))
        deltas = [candidate[identity] - baseline[identity] for identity in paired]
        sign = -1 if name in lower else 1
        result[name] = MetricDiagnostic(
            direction="lower_is_better" if name in lower else "higher_is_better",
            case_count=len(cases),
            baseline_count=len(baseline),
            candidate_count=len(candidate),
            valid_pair_count=len(paired),
            missing_pair_count=len(cases) - len(paired),
            candidate_wins=sum(delta * sign > 0 for delta in deltas),
            candidate_losses=sum(delta * sign < 0 for delta in deltas),
            ties=sum(delta == 0 for delta in deltas),
            mean_paired_delta=math.fsum(delta / len(deltas) for delta in deltas)
            if deltas
            else None,
        )
    return result
