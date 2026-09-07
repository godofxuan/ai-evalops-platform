"""Thin worker adapter for versioned product observations and scores."""

import json
from typing import ClassVar, Literal

from app.domain.evaluation import EvaluationCase, EvaluationResult, TargetResult
from app.product_experiments.evaluators import registered_evaluators
from app.product_experiments.runner import (
    ExperimentCase,
    normalize_product_observation,
    score_product_case,
)


def restore_product_case(case: EvaluationCase) -> ExperimentCase:
    original = case.metadata.get("evalops_product_case")
    restored = ExperimentCase.model_validate_json(json.dumps(original))
    if (
        restored.case_id != case.case_id
        or restored.prompt != case.question
        or restored.reference_answer != case.expected_answer
    ):
        raise ValueError("product/core case identity mismatch")
    return restored


def product_input_requirements(
    case: ExperimentCase, *, task_type: Literal["QA", "AGENT_TOOL_USE"]
) -> list[str]:
    if task_type == "QA":
        return [] if case.expected_citation_ids else ["MISSING_CITATION_LABELS"]
    if "allowed_tools" not in case.model_fields_set or case.max_tool_calls is None:
        return ["MISSING_AGENT_EXPECTATIONS"]
    if (
        any(call.name not in case.allowed_tools for call in case.expected_tool_calls)
        or len(case.expected_tool_calls) > case.max_tool_calls
    ):
        return ["INCONSISTENT_AGENT_EXPECTATIONS"]
    return []


class ProductQAEvaluator:
    task_type: ClassVar[Literal["QA", "AGENT_TOOL_USE"]] = "QA"
    evaluator_names: ClassVar[tuple[str, ...]] = (
        "reference_answer",
        "citation_correctness",
        "tool_error_rate",
    )

    def evaluate(
        self, case: EvaluationCase, target_result: TargetResult, *, attempt_number: int
    ) -> EvaluationResult:
        del attempt_number  # Identity and fencing remain owned by the existing worker.
        product_case = restore_product_case(case)
        observation = normalize_product_observation(
            product_case, target_result, task_type=self.task_type
        )
        missing = product_input_requirements(product_case, task_type=self.task_type)
        if observation.cost_usd is None:
            missing.append("MISSING_COST_MEASUREMENT")
        if self.task_type == "AGENT_TOOL_USE" and observation.missing_fields:
            missing.append("MISSING_AGENT_OBSERVATION")
        scores = (
            {}
            if missing
            else score_product_case(
                product_case,
                observation,
                evaluators=registered_evaluators(self.evaluator_names),
            )
        )
        return EvaluationResult(
            metrics={
                "product_schema_version": "evalops.worker-product-observation/2.0",
                "product_task_type": self.task_type,
                "product_status": "INSUFFICIENT_EVIDENCE" if missing else "OBSERVED",
                "product_missing": missing,
                "product_scores": scores,
                "product_observation": observation.model_dump(mode="json"),
            }
        )


class ProductAgentEvaluator(ProductQAEvaluator):
    task_type = "AGENT_TOOL_USE"
    evaluator_names = (
        "agent_task_completion",
        "tool_selection_accuracy",
        "tool_argument_validity",
        "policy_violation_rate",
        "tool_budget_violation_rate",
        "tool_error_rate",
    )
