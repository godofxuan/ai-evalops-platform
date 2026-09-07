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
        original = case.metadata.get("evalops_product_case")
        product_case = ExperimentCase.model_validate_json(json.dumps(original))
        if (
            product_case.case_id != case.case_id
            or product_case.prompt != case.question
            or product_case.reference_answer != case.expected_answer
        ):
            raise ValueError("product/core case identity mismatch")
        observation = normalize_product_observation(
            product_case, target_result, task_type=self.task_type
        )
        missing = []
        if observation.cost_usd is None:
            missing.append("MISSING_COST_MEASUREMENT")
        if self.task_type == "QA" and not product_case.expected_citation_ids:
            missing.append("MISSING_CITATION_LABELS")
        if self.task_type == "AGENT_TOOL_USE":
            if observation.missing_fields:
                missing.append("MISSING_AGENT_OBSERVATION")
            if (
                "allowed_tools" not in product_case.model_fields_set
                or product_case.max_tool_calls is None
            ):
                missing.append("MISSING_AGENT_EXPECTATIONS")
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
