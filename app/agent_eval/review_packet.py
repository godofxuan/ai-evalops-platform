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
_INPUT_FIELDS = {"message", "question", "expected_answer"}
_CITATION_FIELDS = {"quote", "text", "title", "url", "page", "span"}
_SOURCE_FIELDS = {"title", "url", "excerpt", "content", "page"}


def build_agent_review_packet(
    artifact: AgentRunArtifact,
    *,
    evaluator_results: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded packet with selected runtime identifiers omitted."""

    del evaluator_results

    return {
        "case_id": artifact.case_id,
        "input": _allowlisted_mapping(artifact.input, _INPUT_FIELDS),
        "final_answer": artifact.output.get("answer"),
        "citations": _allowlisted_items(artifact.evidence.get("citations", []), _CITATION_FIELDS),
        "sources": _allowlisted_items(artifact.evidence.get("sources", []), _SOURCE_FIELDS),
        "terminal_state": artifact.terminal.state,
        "trajectory": [
            {"event_type": event.event_type}
            for event in artifact.trajectory
            if event.event_type in _VISIBLE_EVENT_TYPES
        ],
    }


def _allowlisted_items(value: object, fields: set[str]) -> list[object]:
    if not isinstance(value, list):
        return []
    return [
        sanitized
        for item in value
        if isinstance(item, dict) and (sanitized := _allowlisted_mapping(item, fields))
    ]


def _allowlisted_mapping(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in sorted(value.items())
        if key in fields and _is_bounded_json_value(item)
    }


def _is_bounded_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return len(value) <= 20 and all(_is_bounded_json_value(item) for item in value)
    return False
