"""Fail-closed, loss-accounted conversion from Inspect AI logs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel

from app.agent_eval.schema import (
    AgentRunArtifact,
    AgentTerminal,
    TerminalState,
    TrajectoryEvent,
    TrajectoryEventType,
)


class InspectLogContractError(ValueError):
    """The external log cannot be interpreted without guessing."""


_SUPPORTED_VERSION = 2
_SUPPORTED_EVENTS = frozenset(
    {
        "sample_init",
        "sample_limit",
        "sandbox",
        "state",
        "store",
        "model",
        "tool",
        "anchor",
        "approval",
        "branch",
        "checkpoint",
        "compaction",
        "input",
        "interrupt",
        "score",
        "score_edit",
        "error",
        "logger",
        "info",
        "span_begin",
        "span_end",
        "step",
        "subtask",
    }
)


def convert_inspect_log_to_artifact(
    log: object,
    *,
    sample_index: int,
    mode: Literal["formal", "diagnostic"] = "formal",
) -> AgentRunArtifact:
    """Convert one Inspect sample with an explicit supported-event registry."""

    payload = _json_mapping(log, "log")
    version = payload.get("version")
    if version != _SUPPORTED_VERSION or isinstance(version, bool):
        raise InspectLogContractError(f"unsupported Inspect log version: {version!r}")
    status = payload.get("status")
    if status not in {"success", "error", "cancelled", "started"}:
        raise InspectLogContractError(f"unsupported Inspect log status: {status!r}")
    if mode == "formal" and status != "success":
        raise InspectLogContractError(
            f"formal conversion requires terminal success status, got {status!r}"
        )
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
    completion = _completion(sample.get("output"), partial=status != "success")
    trajectory, unmapped_count = _trajectory(sample.get("events"), mode=mode)
    scores = _json_safe_mapping(sample.get("scores", {}), "scores")
    source_identity = _sha256(
        {
            "eval_id": eval_id,
            "sample_index": sample_index,
            "case_id": case_id,
            "version": version,
        }
    )
    terminal_state = {
        "success": "answer",
        "error": "agent_error",
        "cancelled": "agent_error",
        "started": "partial",
    }[cast(str, status)]
    source_count = len(sample.get("events") or [])
    partial = status != "success"
    formal_gate_eligible = not partial and unmapped_count == 0
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
            "inspect_status": status,
            "conversion_mode": mode,
            "model": model,
            "sample_index": sample_index,
            "source_identity_sha256": source_identity,
            "source_event_count": source_count,
            "converted_event_count": len(trajectory),
            "unmapped_event_count": unmapped_count,
            "dropped_event_count": 0,
            "partial": partial,
            "formal_gate_eligible": formal_gate_eligible,
            "loss_manifest": (
                []
                if unmapped_count == 0
                else [{"reason": "unknown_event_preserved_raw", "count": unmapped_count}]
            ),
        },
    )


def _trajectory(
    raw_events: object,
    *,
    mode: Literal["formal", "diagnostic"],
) -> tuple[list[TrajectoryEvent], int]:
    if raw_events is None:
        return [], 0
    if not isinstance(raw_events, list):
        raise InspectLogContractError("sample events must be a list")
    converted: list[TrajectoryEvent] = []
    seen_ids: set[str] = set()
    prior_timestamp: datetime | None = None
    unmapped_count = 0
    for index, raw_event in enumerate(raw_events):
        event = _json_mapping(raw_event, f"events[{index}]")
        kind = event.get("event")
        if not isinstance(kind, str):
            raise InspectLogContractError(f"events[{index}].event is missing")
        if kind not in _SUPPORTED_EVENTS:
            if mode == "formal":
                raise InspectLogContractError(f"unsupported Inspect event: {kind!r}")
            unmapped_count += 1
        event_id = _event_id(event, index)
        if event_id in seen_ids:
            raise InspectLogContractError(f"duplicate Inspect event id: {event_id}")
        seen_ids.add(event_id)
        timestamp = _event_timestamp(event)
        if timestamp is not None:
            if prior_timestamp is not None and timestamp < prior_timestamp:
                raise InspectLogContractError("Inspect events are out of timestamp order")
            prior_timestamp = timestamp
        converted.append(_convert_event(event, index, kind, event_id))
    return converted, unmapped_count


def _convert_event(
    event: Mapping[str, Any],
    index: int,
    kind: str,
    event_id: str,
) -> TrajectoryEvent:
    event_type = cast(
        TrajectoryEventType,
        {
            "tool": "tool_call",
            "input": "user_message",
            "interrupt": "interrupt",
            "approval": "policy_decision",
        }.get(kind, "model_step"),
    )
    tool_name: str | None = None
    if kind == "tool":
        tool_name = _required_text(event, "function")
    return TrajectoryEvent(
        event_id=event_id,
        event_type=event_type,
        tool_name=tool_name,
        payload={
            "inspect_event_type": kind,
            "inspect_event_index": index,
            "inspect_event": _json_safe_mapping(event, f"events[{index}]"),
        },
    )


def _event_id(event: Mapping[str, Any], index: int) -> str:
    for key in ("uuid", "id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return f"inspect-event-{index}"


def _event_timestamp(event: Mapping[str, Any]) -> datetime | None:
    value = event.get("timestamp")
    if value is None:
        return None
    if not isinstance(value, str):
        raise InspectLogContractError("Inspect event timestamp must be an ISO string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InspectLogContractError("Inspect event timestamp is invalid") from error


def _completion(output: object, *, partial: bool) -> str:
    if output is None and partial:
        return ""
    if isinstance(output, str):
        return output
    mapping = _json_mapping(output, "output")
    value = mapping.get("completion")
    if value is None and partial:
        return ""
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
