from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_eval.schema import (
    AgentRunArtifact,
    ArtifactSchemaVersion,
    FrameworkName,
    OpaqueIdentifier,
)

AgentEvaluatorKind = Literal[
    "task_success",
    "tool_call_validity",
    "trajectory_efficiency",
    "grounding_citation",
    "permission_boundary",
    "terminal_state",
    "cost_latency",
]


class AgentArtifactUpload(BaseModel):
    """Validated upload; identity is derived from the authenticated Principal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    artifact: AgentRunArtifact


class AgentArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    case_id: OpaqueIdentifier
    schema_version: ArtifactSchemaVersion
    framework: FrameworkName
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminal_state: str | None
    created_at: datetime


class AgentArtifactDetailRead(BaseModel):
    id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact: AgentRunArtifact


class AgentArtifactEvaluationRequest(BaseModel):
    """An explicit, bounded evaluator set for one immutable trajectory artifact."""

    model_config = ConfigDict(extra="forbid", strict=True)

    evaluators: list[AgentEvaluatorKind] = Field(min_length=1, max_length=7)
    config: dict[AgentEvaluatorKind, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evaluator_names_are_unique_and_configs_are_selected(
        self,
    ) -> "AgentArtifactEvaluationRequest":
        if len(self.evaluators) != len(set(self.evaluators)):
            raise ValueError("evaluator names must be unique")
        if not set(self.config).issubset(self.evaluators):
            raise ValueError("configuration is only allowed for selected evaluators")
        return self


class AgentArtifactEvaluationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_id: UUID
    evaluator_kind: AgentEvaluatorKind
    evaluator_version: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, Any]
    failure_taxonomy: list[str]
    created_at: datetime


class AgentRegressionGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_success_min: float | None = Field(default=None, ge=0, le=1)
    permission_violation_max: int | None = Field(default=None, ge=0)
    latency_p95_max_regression_pct: float | None = Field(default=None, ge=0)
    tool_error_rate_max: float | None = Field(default=None, ge=0, le=1)


class AgentRegressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_run_id: UUID
    right_run_id: UUID
    gate: AgentRegressionGateConfig

    @model_validator(mode="after")
    def run_ids_must_differ(self) -> "AgentRegressionRequest":
        if self.left_run_id == self.right_run_id:
            raise ValueError("left and right Run IDs must differ")
        return self


class AgentRegressionResponse(BaseModel):
    intersection_count: int
    left_only_count: int
    right_only_count: int
    task_success_rate: dict[str, float | None]
    latency_p95_ms: dict[str, float | None]
    permission_violation_count: dict[str, int]
    terminal_distribution: dict[str, dict[str, int]]
    failure_category_distribution: dict[str, dict[str, int]]
    gate_passed: bool
    gate_violations: list[str]
