"""Versioned adapter for the Enterprise RAG external harness contract."""

from __future__ import annotations

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


class _ProducerArtifact(_StrictModel):
    schema_name: Literal["enterprise.agent-run"]
    schema_version: Literal["1.0"]
    run_id: str = Field(min_length=1, max_length=200)
    case_id: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: str | None = None
    session_id: str = Field(min_length=1, max_length=200)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    trace_context: _TraceContext
    input: dict[str, JsonValue] = Field(default_factory=dict)
    output: dict[str, JsonValue] = Field(default_factory=dict)
    trajectory: list[dict[str, JsonValue]]
    retrieval: dict[str, JsonValue]
    evidence: dict[str, JsonValue]
    usage: dict[str, JsonValue]
    terminal: dict[str, JsonValue]
    source_trajectory_root_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class _ToolEvent(_StrictModel):
    event_type: Literal["tool.requested", "tool.completed", "tool.failed"]
    tool_name: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.:-]+$")
    sequence: int = Field(ge=0)
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
    def trace_identity_matches_artifact(self) -> RagHarnessResultV1:
        trace = self.trajectory_artifact.trace_context
        if (self.trace_id, self.root_span_id) != (trace.trace_id, trace.root_span_id):
            raise ValueError("harness and trajectory trace identities differ")
        if self.propagated_traceparent.split("-")[1] != self.trace_id:
            raise ValueError("traceparent does not propagate the harness trace")
        if self.trajectory_artifact.trace_id not in {None, self.trace_id}:
            raise ValueError("artifact top-level trace identity differs")
        if self.trajectory_artifact.case_id not in {None, self.case_id}:
            raise ValueError("harness and trajectory case identities differ")
        return self


def convert_rag_harness_result(result: object) -> AgentRunArtifact:
    """Validate harness/trajectory identities before producing an EvalOps artifact."""

    try:
        parsed = RagHarnessResultV1.model_validate(result)
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
    trajectory = [
        TrajectoryEvent(
            event_id=f"rag-tool-{event.sequence}",
            event_type=cast(
                TrajectoryEventType,
                {
                    "tool.requested": "tool_call",
                    "tool.completed": "tool_result",
                    "tool.failed": "tool_result",
                }[event.event_type],
            ),
            tool_name=event.tool_name,
            payload={
                "producer_event_type": event.event_type,
                "producer_sequence": event.sequence,
                **event.payload,
            },
        )
        for event in parsed.tool_events
    ]
    return AgentRunArtifact(
        schema_version="agent-run-artifact/v1",
        run_id=producer.run_id,
        case_id=parsed.case_id,
        session_id=producer.session_id,
        framework="enterprise-rag-agent-runtime",
        input=producer.input,
        output={
            "answer": parsed.answer,
            "citations": cast(JsonValue, parsed.citations),
        },
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
            "policy_decisions": [item.model_dump(mode="json") for item in parsed.policy_decisions],
        },
    )


__all__ = [
    "RagHarnessContractError",
    "RagHarnessResultV1",
    "convert_rag_harness_result",
]
