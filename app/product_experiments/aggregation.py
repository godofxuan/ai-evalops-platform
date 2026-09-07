"""Pure result aggregation from already captured observations; never executes a target."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.external_harness.formal_quality import FormalQualityPolicy
from app.product_experiments.assessment import assess_product_numeric
from app.product_experiments.diagnostics import build_category_diagnostics, build_metric_diagnostics
from app.product_experiments.evaluators import registered_evaluators
from app.product_experiments.measurements import ProductArmResult, ProductCaseMeasurement
from app.product_experiments.runner import (
    CaseExecutionFailure,
    ExperimentCase,
    ProductExperimentResult,
    ProviderResult,
    _agent_assessment,
    _comparisons,
    _measurement,
    score_product_case,
)
from app.product_experiments.spec import AgentComparisonPolicy

ARM_LABELS: tuple[Literal["baseline", "candidate"], ...] = ("baseline", "candidate")


@dataclass(frozen=True, slots=True)
class ProductAggregationContext:
    experiment_id: str
    execution_id: UUID | None
    scope: Literal["DEMO", "FORMAL"]
    task_type: Literal["QA", "AGENT_TOOL_USE"]
    dataset_sha256: str
    evalops_sha: str
    source_identities: dict[str, dict[str, str]]
    input_snapshot: dict[str, Any] | None
    policy: FormalQualityPolicy
    agent_comparison_policy: AgentComparisonPolicy
    citation_precision_min: float
    evaluator_names: tuple[str, ...]


def aggregate_product_observations(
    *,
    context: ProductAggregationContext,
    cases: list[ExperimentCase],
    observations: dict[str, dict[str, ProviderResult]],
    execution_errors: list[CaseExecutionFailure],
    execution_schedule: list[dict[str, Any]] | None = None,
    execution_events: list[dict[str, Any]] | None = None,
) -> ProductExperimentResult:
    identities = {case.case_id for case in cases}
    if len(identities) != len(cases) or not 2 <= len(cases) <= 10000:
        raise ValueError("aggregation requires a bounded unique case set")
    if set(observations) != {"baseline", "candidate"} or any(
        not set(rows) <= identities for rows in observations.values()
    ):
        raise ValueError("observations do not belong to the paired case set")
    failures = list(execution_errors)
    failed = {(error.arm, error.case_id) for error in failures}
    if len(failed) != len(failures) or any(
        identity not in identities or identity in observations[arm] for arm, identity in failed
    ):
        raise ValueError("execution failures conflict with accepted observations")
    evaluators = registered_evaluators(context.evaluator_names)
    requirements: list[dict[str, str]] = []
    measurements: dict[str, list[ProductCaseMeasurement]] = {"baseline": [], "candidate": []}
    scores: dict[str, dict[str, dict[str, float]]] = {"baseline": {}, "candidate": {}}
    for arm in ARM_LABELS:
        for case in cases:
            observation = observations[arm].get(case.case_id)
            if observation is None:
                if (arm, case.case_id) not in failed:
                    failures.append(
                        CaseExecutionFailure(
                            arm=arm,
                            case_id=case.case_id,
                            error_code="accepted_observation_missing",
                            retryable=False,
                        )
                    )
                continue
            if observation.cost_usd is None:
                requirements.append(
                    {"arm": arm, "case_id": case.case_id, "code": "MISSING_COST_MEASUREMENT"}
                )
                continue
            if context.task_type == "AGENT_TOOL_USE" and observation.missing_fields:
                requirements.append(
                    {
                        "arm": arm,
                        "case_id": case.case_id,
                        "code": "MISSING_AGENT_OBSERVATION",
                        "fields": ",".join(observation.missing_fields),
                    }
                )
                continue
            case_scores = score_product_case(case, observation, evaluators=evaluators)
            scores[arm][case.case_id] = case_scores
            measurements[arm].append(
                _measurement(case, observation, scores=case_scores, task_type=context.task_type)
            )
    common: dict[str, Any] = {
        "experiment_id": context.experiment_id,
        "execution_id": context.execution_id,
        "scope": context.scope,
        "task_type": context.task_type,
        "dataset_sha256": context.dataset_sha256,
        "evalops_sha": context.evalops_sha,
        "source_identities": context.source_identities,
        "input_snapshot": context.input_snapshot,
        "case_count": len(cases),
        "observations": observations,
        "execution_schedule": execution_schedule or [],
        "execution_events": execution_events or [],
        "metric_diagnostics": build_metric_diagnostics(
            cases, observations, evaluator_names=context.evaluator_names
        ),
        "category_diagnostics": build_category_diagnostics(
            cases,
            observations,
            evaluator_names=context.evaluator_names,
            minimum_cases=context.policy.minimum_cases_per_category,
            required_categories=context.policy.required_categories,
        ),
    }
    if failures or requirements:
        return ProductExperimentResult(
            **common,
            status="EXECUTION_FAILED" if failures else "INSUFFICIENT_EVIDENCE",
            arms={},
            automated_assessment={"status": "NOT_RUN", "reason": "observations_incomplete"},
            case_comparisons=[],
            input_requirements=sorted(requirements, key=lambda row: (row["arm"], row["case_id"])),
            execution_errors=sorted(failures, key=lambda row: (row.arm, row.case_id)),
        )
    arms = {
        arm: ProductArmResult(
            arm=arm,
            source_sha=context.source_identities[arm]["sha"],
            dataset_sha256=context.dataset_sha256,
            cases=measurements[arm],
        )
        for arm in ARM_LABELS
    }
    assessment = assess_product_numeric(
        arms["baseline"],
        arms["candidate"],
        policy=context.policy,
        task_type=context.task_type,
        citation_precision_min=context.citation_precision_min,
    )
    agent = (
        _agent_assessment(scores, policy=context.agent_comparison_policy)
        if context.task_type == "AGENT_TOOL_USE"
        else None
    )
    passed = assessment["status"] == "PASS" and (agent is None or agent["status"] == "PASS")
    result_status: Literal[
        "DEMO_PASS",
        "DEMO_FAIL",
        "AUTOMATED_PASS_HUMAN_REVIEW_PENDING",
        "AUTOMATED_FAIL",
        "INSUFFICIENT_EVIDENCE",
    ]
    if assessment["status"] == "INSUFFICIENT_EVIDENCE":
        result_status = "INSUFFICIENT_EVIDENCE"
    elif context.scope == "DEMO":
        result_status = "DEMO_PASS" if passed else "DEMO_FAIL"
    else:
        result_status = "AUTOMATED_PASS_HUMAN_REVIEW_PENDING" if passed else "AUTOMATED_FAIL"
    return ProductExperimentResult(
        **common,
        status=result_status,
        arms={"baseline": arms["baseline"], "candidate": arms["candidate"]},
        automated_assessment=assessment,
        agent_tool_use_assessment=agent,
        case_comparisons=_comparisons(
            arms["baseline"],
            arms["candidate"],
            provider_results=observations,
            score_results=scores,
            task_type=context.task_type,
        ),
    )
