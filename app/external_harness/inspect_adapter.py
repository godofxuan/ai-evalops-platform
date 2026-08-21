"""Fail-closed conversion from Inspect AI evaluation logs to EvalOps artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel

from app.agent_eval.schema import (
    AgentRunArtifact,
    AgentTerminal,
    TerminalState,
    TrajectoryEvent,
)


class InspectLogContractError(ValueError):
    """The external log cannot be interpreted without guessing."""


def convert_inspect_log_to_artifact(
    log: object,
    *,
    sample_index: int,
) -> AgentRunArtifact:
    """Convert one Inspect sample while preserving source identity and provenance."""

    payload = _json_mapping(log, "log")
    version = payload.get("version")
    if not isinstance(version, (int, str)) or isinstance(version, bool):
        raise InspectLogContractError("Inspect log version is missing or invalid")
    status = payload.get("status")
    if status not in {"success", "error", "cancelled", "started"}:
        raise InspectLogContractError(f"unsupported Inspect log status: {status!r}")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise InspectLogContractError("Inspect log contains no samples")
    try:
        sample = _json_mapping(samples[sample_index], f"samples[{sample_index}]")
    except IndexError as error:
        raise InspectLogContractError("Inspect sample index is out of range") from error
    evaluation = _json_mapping(payload.get("eval"), "eval")

    case_id = _required_text(sample, "id")
    eval_id = _required_text(evaluation, "eval_id")
    task = _required_text(evaluation, "task")
    model = _model_name(evaluation.get("model"))
    completion = _completion(sample.get("output"))
    terminal_state = {
        "success": "answer",
        "error": "agent_error",
        "cancelled": "agent_error",
        "started": "partial",
    }[cast(str, status)]
    trajectory = _trajectory(sample.get("events"))
    scores = _json_safe_mapping(sample.get("scores", {}), "scores")

    source_identity = _sha256(
        {
            "eval_id": eval_id,
            "sample_index": sample_index,
            "case_id": case_id,
            "version": version,
        }
    )
    return AgentRunArtifact(
        schema_version="agent-run-artifact/v1",
        run_id=f"inspect-{eval_id}",
        case_id=case_id,
        session_id=f"inspect-{source_identity[:24]}",
        framework="inspect-ai",
        input={"prompt": _json_safe(sample.get("input"), "input")},
        output={"completion": completion, "scores": scores},
        trajectory=trajectory,
        terminal=AgentTerminal(state=cast(TerminalState, terminal_state)),
        metadata={
            "inspect_eval_id": eval_id,
            "inspect_log_version": version,
            "inspect_task": task,
            "model": model,
            "sample_index": sample_index,
            "source_identity_sha256": source_identity,
        },
    )


def _trajectory(raw_events: object) -> list[TrajectoryEvent]:
    if raw_events is None:
        return []
    if not isinstance(raw_events, list):
        raise InspectLogContractError("sample events must be a list")
    converted: list[TrajectoryEvent] = []
    for index, raw_event in enumerate(raw_events):
        event = _json_mapping(raw_event, f"events[{index}]")
        kind = event.get("event")
        if kind == "tool":
            tool_name = _required_text(event, "function")
            converted.append(
                TrajectoryEvent(
                    event_id=_event_id(event, index),
                    event_type="tool_call",
                    tool_name=tool_name,
                    payload={
                        "arguments": _json_safe(event.get("arguments", {}), "arguments"),
                        "result": _json_safe(event.get("result"), "result"),
                    },
                )
            )
        elif kind in {"model", "message"}:
            converted.append(
                TrajectoryEvent(
                    event_id=_event_id(event, index),
                    event_type="model_step",
                    tool_name=None,
                    payload={"inspect_event": _json_safe_mapping(event, "event")},
                )
            )
    return converted


def _event_id(event: Mapping[str, Any], index: int) -> str:
    value = event.get("id")
    return value if isinstance(value, str) and value else f"inspect-event-{index}"


def _completion(output: object) -> str:
    if isinstance(output, str):
        return output
    mapping = _json_mapping(output, "output")
    value = mapping.get("completion")
    if not isinstance(value, str):
        raise InspectLogContractError("sample output completion is missing")
    return value


def _model_name(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("name", "model"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    raise InspectLogContractError("Inspect model identity is missing")


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
        raise InspectLogContractError(f"{key} is missing or invalid")
    return str(value)


def _json_mapping(value: object, field: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    if not isinstance(value, Mapping):
        raise InspectLogContractError(f"{field} must be an object")
    return dict(value)


def _json_safe_mapping(value: object, field: str) -> dict[str, Any]:
    converted = _json_safe(value, field)
    if not isinstance(converted, dict):
        raise InspectLogContractError(f"{field} must be an object")
    return converted


def _json_safe(value: object, field: str) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise InspectLogContractError(f"{field} is not JSON serializable") from error


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["InspectLogContractError", "convert_inspect_log_to_artifact"]
