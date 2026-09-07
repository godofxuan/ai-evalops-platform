"""Explicit product projection of the existing framework-neutral Agent artifact."""

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.agent_eval.schema import AgentRunArtifact, TrajectoryEvent, artifact_content_sha256
from app.targets.base import TargetInvalidResponseError


def project_agent_trace(
    trace: Mapping[str, Any],
    *,
    case_id: str,
    answer: str | None,
) -> dict[str, Any]:
    if "schema_version" not in trace:
        # Legacy flat observations remain readable, but carry no artifact provenance.
        values = dict(trace)
        flat_calls = values.get("tool_calls")
        if isinstance(flat_calls, list) and any(
            isinstance(call, dict) and "status" not in call for call in flat_calls
        ):
            values["projection_missing_fields"] = ("tool_calls.status",)
        return values
    if trace.get("schema_version") != "agent-run-artifact/v1":
        raise TargetInvalidResponseError("target_agent_schema_unsupported")
    try:
        artifact = AgentRunArtifact.model_validate(dict(trace))
    except ValidationError:
        raise TargetInvalidResponseError("target_agent_artifact_invalid") from None
    if artifact.case_id != case_id or artifact.output.get("answer") != answer:
        raise TargetInvalidResponseError("target_agent_identity_mismatch")
    identities = [event.event_id for event in artifact.trajectory]
    if len(identities) != len(set(identities)):
        raise TargetInvalidResponseError("target_agent_event_identity_duplicate")
    outcomes: dict[str | None, list[TrajectoryEvent]] = defaultdict(list)
    for event in artifact.trajectory:
        if event.event_type == "tool_result":
            outcomes[event.step_id].append(event)
    calls: list[dict[str, Any]] = []
    missing: set[str] = set()
    call_steps: set[str] = set()
    for event in artifact.trajectory:
        if event.event_type != "tool_call":
            continue
        if event.step_id is None or event.step_id in call_steps or event.tool_name is None:
            missing.add("trajectory.tool_call_identity")
            continue
        call_steps.add(event.step_id)
        matches = outcomes.get(event.step_id, [])
        if len(matches) != 1 or matches[0].tool_name != event.tool_name:
            missing.add("trajectory.tool_result")
            continue
        arguments = event.payload.get("arguments")
        success = matches[0].payload.get("success")
        if not isinstance(arguments, dict) or not isinstance(success, bool):
            missing.add("trajectory.arguments_or_success")
            continue
        calls.append(
            {
                "name": event.tool_name,
                "arguments": arguments,
                "status": "success" if success else "error",
            }
        )
    if set(outcomes) - call_steps:
        missing.add("trajectory.unmatched_result")
    terminal = artifact.terminal.state
    values = {
        "trace_id": artifact.session_id,
        "terminal_state": "completed"
        if terminal == "answer"
        else (
            "blocked"
            if terminal in {"refusal", "permission_denied", "budget_exhausted"}
            else "failed"
        ),
        "source_terminal_state": terminal,
        "artifact_sha256": artifact_content_sha256(artifact),
        "tool_calls": calls,
        "tool_error": terminal == "tool_error" or any(call["status"] == "error" for call in calls),
        "budget_exhausted": terminal == "budget_exhausted",
        "projection_missing_fields": tuple(sorted(missing)),
    }
    if artifact.usage.get("currency") == "USD" and "cost" in artifact.usage:
        values["cost_usd"] = artifact.usage["cost"]
    return values
