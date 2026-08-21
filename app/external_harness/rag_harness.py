"""Strict, loss-accounted adapter for the Enterprise RAG producer contract."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.agent_eval.schema import (
    AgentRunArtifact,
    AgentTerminal,
    TerminalState,
    TrajectoryEvent,
    TrajectoryEventType,
)


class RagHarnessContractError(ValueError):
    """The producer response violates the frozen cross-repository contract."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _TraceContext(_StrictModel):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    root_span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    trace_schema_version: Literal["enterprise.agent.telemetry/1.0"]
    content_capture_policy: Literal["off"]
    sanitized_model_metadata: dict[str, JsonValue]
    sanitized_tool_metadata: dict[str, JsonValue]


ProducerEventType = Literal[
    "session.started",
    "user.message",
    "step.started",
    "model.requested",
    "model.responded",
    "tool.requested",
    "tool.completed",
    "tool.failed",
    "retrieval.completed",
    "evidence.admitted",
    "evidence.rejected",
    "claim.proposed",
    "claim.accepted",
    "claim.rejected",
    "citation.checked",
    "budget.updated",
    "human_review.requested",
    "human_review.completed",
    "terminal.reached",
    "session.completed",
]


class _ProducerEvent(_StrictModel):
    schema_version: Literal["1.0"]
    event_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    event_type: ProducerEventType
    timestamp: str
    payload: dict[str, JsonValue]
    step_id: str | None = None
    tool_name: str | None = None
    latency_ms: int | float | None = None
    token_usage: dict[str, JsonValue] | None = None
    cost_usd: int | float | None = None
    error_code: str | None = None
    terminal_reason: str | None = None
    previous_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ProducerArtifact(_StrictModel):
    schema_name: Literal["enterprise.agent-run"]
    schema_version: Literal["1.0"]
    run_id: str = Field(min_length=1, max_length=200)
    case_id: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: str
    session_id: str = Field(min_length=1, max_length=200)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    trace_context: _TraceContext
    input: dict[str, JsonValue] = Field(default_factory=dict)
    output: dict[str, JsonValue] = Field(default_factory=dict)
    trajectory: list[_ProducerEvent] = Field(min_length=1)
    retrieval: dict[str, JsonValue]
    evidence: dict[str, JsonValue]
    usage: dict[str, JsonValue]
    terminal: dict[str, JsonValue]
    source_trajectory_root_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ToolEvent(_StrictModel):
    event_type: Literal["tool.requested", "tool.completed", "tool.failed"]
    tool_name: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.:-]+$")
    sequence: int = Field(ge=1)
    payload: dict[str, JsonValue]


class _PolicyDecision(_StrictModel):
    lifecycle: str
    tool_name: str
    decision: str
    reason_code: str
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RagHarnessResultV1(_StrictModel):
    schema_name: Literal["enterprise.agent-harness-result"]
    schema_version: Literal["1.0"]
    case_id: str = Field(min_length=1, max_length=200)
    attempt_id: str = Field(min_length=1, max_length=200)
    answer: str
    terminal_state: str
    citations: list[dict[str, JsonValue]]
    tool_events: list[_ToolEvent]
    policy_decisions: list[_PolicyDecision]
    trajectory_artifact: _ProducerArtifact
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    root_span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    propagated_traceparent: str = Field(pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
    error_classification: str

    @model_validator(mode="after")
    def identities_match(self) -> RagHarnessResultV1:
        producer = self.trajectory_artifact
        trace = producer.trace_context
        if (self.trace_id, self.root_span_id) != (trace.trace_id, trace.root_span_id):
            raise ValueError("harness and trajectory trace identities differ")
        if self.propagated_traceparent.split("-")[1] != self.trace_id:
            raise ValueError("traceparent does not propagate the harness trace")
        if producer.trace_id not in {None, self.trace_id}:
            raise ValueError("artifact top-level trace identity differs")
        if producer.case_id not in {None, self.case_id}:
            raise ValueError("harness and trajectory case identities differ")
        return self


_EVENT_TYPE_MAP: dict[ProducerEventType, TrajectoryEventType] = {
    "session.started": "model_step",
    "user.message": "user_message",
    "step.started": "model_step",
    "model.requested": "model_step",
    "model.responded": "model_step",
    "tool.requested": "tool_call",
    "tool.completed": "tool_result",
    "tool.failed": "tool_result",
    "retrieval.completed": "model_step",
    "evidence.admitted": "evidence_admission",
    "evidence.rejected": "evidence_rejection",
    "claim.proposed": "claim",
    "claim.accepted": "claim",
    "claim.rejected": "claim",
    "citation.checked": "citation",
    "budget.updated": "model_step",
    "human_review.requested": "interrupt",
    "human_review.completed": "resume",
    "terminal.reached": "terminal_state",
    "session.completed": "terminal_state",
}


def convert_rag_harness_result(result: object) -> AgentRunArtifact:
    """Verify producer digests and convert every source event without silent loss."""

    try:
        parsed = RagHarnessResultV1.model_validate(result)
        _verify_producer_integrity(parsed)
    except ValueError as error:
        raise RagHarnessContractError(str(error)) from error
    producer = parsed.trajectory_artifact
    terminal = {
        "answered": "answer",
        "partial": "partial",
        "unsafe": "refusal",
        "permission": "permission_denied",
        "not_found": "refusal",
        "security_filtered": "refusal",
        "budget": "budget_exhausted",
        "system": "agent_error",
    }.get(parsed.terminal_state)
    if terminal is None:
        raise RagHarnessContractError(
            f"unsupported producer terminal state: {parsed.terminal_state!r}"
        )

    trajectory = [_convert_event(event) for event in producer.trajectory]
    for index, decision in enumerate(parsed.policy_decisions):
        trajectory.append(
            TrajectoryEvent(
                event_id=f"rag-policy-{index + 1}",
                event_type="policy_decision",
                tool_name=decision.tool_name,
                payload=cast(dict[str, JsonValue], decision.model_dump(mode="json")),
            )
        )
    source_count = len(producer.trajectory) + len(parsed.policy_decisions)
    return AgentRunArtifact(
        schema_version="agent-run-artifact/v1",
        run_id=producer.run_id,
        case_id=parsed.case_id,
        session_id=producer.session_id,
        framework="enterprise-rag-agent-runtime",
        input=producer.input,
        output={"answer": parsed.answer, "citations": cast(JsonValue, parsed.citations)},
        trajectory=trajectory,
        retrieval=producer.retrieval,
        evidence=producer.evidence,
        usage=producer.usage,
        terminal=AgentTerminal(
            state=cast(TerminalState, terminal), reason=parsed.error_classification
        ),
        metadata={
            "producer_schema": f"{producer.schema_name}/{producer.schema_version}",
            "producer_git_sha": producer.git_sha,
            "attempt_id": parsed.attempt_id,
            "trace_id": parsed.trace_id,
            "root_span_id": parsed.root_span_id,
            "traceparent": parsed.propagated_traceparent,
            "producer_artifact_sha256": producer.artifact_sha256,
            "producer_trajectory_root_hash": producer.source_trajectory_root_hash,
            "integrity_verification": "verified",
            "source_event_count": source_count,
            "converted_event_count": len(trajectory),
            "unmapped_event_count": 0,
            "dropped_event_count": 0,
            "loss_manifest": [],
        },
    )


def _verify_producer_integrity(parsed: RagHarnessResultV1) -> None:
    producer = parsed.trajectory_artifact
    seen_ids: set[str] = set()
    previous: str | None = None
    previous_timestamp: datetime | None = None
    derived_tools: list[dict[str, JsonValue]] = []
    for expected_sequence, event in enumerate(producer.trajectory, start=1):
        if event.sequence != expected_sequence:
            raise ValueError("producer trajectory sequence is not contiguous and ordered")
        if event.event_id in seen_ids:
            raise ValueError("producer trajectory contains duplicate event_id")
        seen_ids.add(event.event_id)
        if event.session_id != producer.session_id or event.trace_id != parsed.trace_id:
            raise ValueError("producer event identity differs from artifact identity")
        if event.previous_hash != previous:
            raise ValueError("producer trajectory previous_hash chain is invalid")
        timestamp = _timestamp(event.timestamp)
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("producer trajectory timestamps are out of order")
        previous_timestamp = timestamp
        expected_hash = _canonical_sha256(event.model_dump(mode="json", exclude={"event_hash"}))
        if event.event_hash != expected_hash:
            raise ValueError("producer trajectory event digest mismatch")
        previous = event.event_hash
        if event.event_type in {"tool.requested", "tool.completed", "tool.failed"}:
            if not event.tool_name:
                raise ValueError("producer tool event omitted tool_name")
            derived_tools.append(
                {
                    "event_type": event.event_type,
                    "tool_name": event.tool_name,
                    "sequence": event.sequence,
                    "payload": event.payload,
                }
            )
    if producer.source_trajectory_root_hash != previous:
        raise ValueError("producer trajectory root hash mismatch")
    supplied_tools = [event.model_dump(mode="json") for event in parsed.tool_events]
    if supplied_tools != derived_tools:
        raise ValueError("top-level tool_events differ from producer trajectory")
    expected_artifact_digest = _canonical_sha256(
        producer.model_dump(mode="json", exclude={"artifact_sha256"})
    )
    if producer.artifact_sha256 != expected_artifact_digest:
        raise ValueError("producer artifact digest mismatch")


def _convert_event(event: _ProducerEvent) -> TrajectoryEvent:
    payload = cast(dict[str, JsonValue], event.model_dump(mode="json"))
    return TrajectoryEvent(
        event_id=event.event_id,
        event_type=_EVENT_TYPE_MAP[event.event_type],
        step_id=event.step_id,
        tool_name=event.tool_name,
        payload=payload,
    )


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("producer event timestamp is invalid") from error


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "RagHarnessContractError",
    "RagHarnessResultV1",
    "convert_rag_harness_result",
]
