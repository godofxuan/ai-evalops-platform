"""Versioned, framework-neutral Agent execution artifact contract."""

import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ArtifactSchemaVersion = Literal["agent-run-artifact/v1"]
TrajectoryEventType = Literal[
    "user_message",
    "model_step",
    "tool_call",
    "tool_result",
    "evidence_admission",
    "evidence_rejection",
    "claim",
    "citation",
    "policy_decision",
    "interrupt",
    "resume",
    "terminal_state",
]
TerminalState = Literal[
    "answer",
    "partial",
    "refusal",
    "permission_denied",
    "budget_exhausted",
    "tool_error",
    "agent_error",
]
OpaqueIdentifier = Annotated[str, Field(min_length=1, max_length=200)]
FrameworkName = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")]


class TrajectoryEvent(BaseModel):
    """One semantic Agent execution event, independent of the runtime framework."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: OpaqueIdentifier
    event_type: TrajectoryEventType
    step_id: OpaqueIdentifier | None = None
    tool_name: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.:-]+$"),
    ]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class AgentTerminal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: TerminalState
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class AgentRunArtifact(BaseModel):
    """Immutable semantic record emitted by an Agent runtime for one evaluation case."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: ArtifactSchemaVersion
    run_id: OpaqueIdentifier
    case_id: OpaqueIdentifier
    session_id: OpaqueIdentifier
    framework: FrameworkName
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    trajectory: list[TrajectoryEvent]
    retrieval: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    terminal: AgentTerminal
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def numeric_evidence_is_nonnegative_and_finite(self) -> "AgentRunArtifact":
        for key in (
            "latency_ms",
            "tool_latency_ms",
            "cost",
            "input_tokens",
            "output_tokens",
            "model_calls",
            "step_count",
        ):
            if key in self.usage:
                _require_nonnegative_finite(self.usage[key], f"usage.{key}")
        for index, event in enumerate(self.trajectory):
            for key in ("depth", "step_count"):
                if key in event.payload:
                    _require_nonnegative_finite(
                        event.payload[key], f"trajectory[{index}].payload.{key}"
                    )
        return self


def artifact_content_sha256(artifact: AgentRunArtifact) -> str:
    """Return the content identity over a canonical JSON representation."""

    canonical = canonical_artifact_bytes(artifact)
    return hashlib.sha256(canonical).hexdigest()


def canonical_artifact_bytes(artifact: AgentRunArtifact) -> bytes:
    return json.dumps(
        artifact.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_nonnegative_finite(value: JsonValue, field_name: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative finite number")
