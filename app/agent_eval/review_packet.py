"""Blinded, bounded Agent review packets for the existing human-review workflow."""

from typing import Any

from app.agent_eval.schema import AgentRunArtifact

_VISIBLE_EVENT_TYPES = {
    "tool_call",
    "tool_result",
    "evidence_admission",
    "citation",
    "terminal_state",
}


def build_agent_review_packet(
    artifact: AgentRunArtifact,
    *,
    evaluator_results: dict[str, Any],
) -> dict[str, Any]:
    """Build a review-safe packet without framework/candidate identity or raw model-step content."""

    return {
        "case_id": artifact.case_id,
        "input": artifact.input,
        "final_answer": artifact.output.get("answer"),
        "citations": artifact.evidence.get("citations", []),
        "sources": artifact.evidence.get("sources", []),
        "terminal_state": artifact.terminal.state,
        "trajectory": [
            {"event_type": event.event_type, "tool_name": event.tool_name}
            for event in artifact.trajectory
            if event.event_type in _VISIBLE_EVENT_TYPES
        ],
        "evaluator_results": evaluator_results,
    }
