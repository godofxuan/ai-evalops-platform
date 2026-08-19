"""Small, evidence-led taxonomy for Agent execution failures."""

from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    RETRIEVAL_FAILURE = "retrieval_failure"
    TOOL_FAILURE = "tool_failure"
    PERMISSION_FAILURE = "permission_failure"
    PLANNING_FAILURE = "planning_failure"
    GROUNDING_FAILURE = "grounding_failure"
    CITATION_FAILURE = "citation_failure"
    CONTEXT_FAILURE = "context_failure"
    BUDGET_FAILURE = "budget_failure"
    LOOP_FAILURE = "loop_failure"
    MODEL_FAILURE = "model_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


def classify_agent_failure(metrics: dict[str, Any]) -> FailureCategory | None:
    """Classify only when an observed artifact metric supports a category.

    This is attribution, not a root-cause claim. Callers retain the evaluator metrics and
    trajectory.
    """

    if _positive(metrics.get("unauthorized_result_leak_count")) or _terminal_is(
        metrics, "permission_denied"
    ):
        return FailureCategory.PERMISSION_FAILURE
    if _positive(metrics.get("tool_calls_error")) or _terminal_is(metrics, "tool_error"):
        return FailureCategory.TOOL_FAILURE
    if _positive(metrics.get("citation_invalid_count")):
        return FailureCategory.CITATION_FAILURE
    if _positive(metrics.get("unsupported_claim_count")):
        return FailureCategory.GROUNDING_FAILURE
    if _positive(metrics.get("repeated_tool_call_count")):
        return FailureCategory.LOOP_FAILURE
    if _terminal_is(metrics, "budget_exhausted"):
        return FailureCategory.BUDGET_FAILURE
    if _terminal_is(metrics, "agent_error"):
        return FailureCategory.MODEL_FAILURE
    if metrics.get("task_success_requires_human_review") is True:
        return FailureCategory.HUMAN_REVIEW_REQUIRED
    return None


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _terminal_is(metrics: dict[str, Any], expected: str) -> bool:
    return metrics.get("terminal_state") == expected
