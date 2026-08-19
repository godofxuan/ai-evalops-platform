"""Versioned, framework-neutral Agent execution artifact contract."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
    "terminal_state",
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
    terminal: dict[str, JsonValue]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


def artifact_content_sha256(artifact: AgentRunArtifact) -> str:
    """Return the content identity over a canonical JSON representation."""

    canonical = json.dumps(
        artifact.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
