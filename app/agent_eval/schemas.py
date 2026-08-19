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
AgentCaseSetPolicy = Literal["exact", "intersection", "allow-diff"]
AgentMissingMetricPolicy = Literal["fail", "warn", "ignore"]


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
    metric_provenance: dict[str, Literal["reported", "derived", "verified"]]
    failure_taxonomy: list[str]
    created_at: datetime


class AgentRegressionGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_success_min: float | None = Field(default=None, ge=0, le=1)
    permission_violation_max: int | None = Field(default=None, ge=0)
    latency_p95_max_regression_pct: float | None = Field(default=None, ge=0)
    tool_error_rate_max: float | None = Field(default=None, ge=0, le=1)
    minimum_intersection_count: int = Field(default=1, ge=1)
    minimum_metric_sample_count: int = Field(default=2, ge=1)
    minimum_metric_coverage: float = Field(default=1.0, gt=0, le=1)
    missing_metric_policy: AgentMissingMetricPolicy = "fail"
    case_set_policy: AgentCaseSetPolicy = "exact"
    allow_reported_evidence: bool = False


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
    comparison_id: UUID
    left_run_id: UUID
    right_run_id: UUID
    case_set_policy: AgentCaseSetPolicy
    common_case_ids: list[str]
    common_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    intersection_count: int
    left_only_case_ids: list[str]
    right_only_case_ids: list[str]
    left_only_count: int
    right_only_count: int
    common_case_metrics: "AgentCommonCaseMetricsRead"
    left_full_run_diagnostics: "AgentRunDiagnosticsRead"
    right_full_run_diagnostics: "AgentRunDiagnosticsRead"
    evidence_manifest: list["AgentComparisonEvidenceRead"]
    gate_executed: bool
    evidence_sufficient: bool
    gate_status: Literal["passed", "failed", "insufficient_evidence", "case_set_mismatch"]
    gate_passed: bool
    gate_violations: list[str]
    warnings: list[str]
    created_at: datetime


class AgentMetricEvidenceRead(BaseModel):
    sample_count: dict[str, int]
    coverage: dict[str, float]
    missing_count: dict[str, int]


class AgentCommonCaseMetricsRead(BaseModel):
    task_success_rate: dict[str, float | None]
    latency_p95_ms: dict[str, float | None]
    unauthorized_result_leak_count: dict[str, int]
    tool_error_rate: dict[str, float | None]
    terminal_distribution: dict[str, dict[str, int]]
    failure_category_distribution: dict[str, dict[str, int]]
    metric_evidence: dict[str, AgentMetricEvidenceRead]
    metric_trust: dict[str, dict[str, dict[str, int]]]


class AgentRunDiagnosticsRead(BaseModel):
    case_count: int
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_success_rate: float | None
    latency_p95_ms: float | None
    terminal_distribution: dict[str, int]
    failure_category_distribution: dict[str, int]


class AgentComparisonEvidenceRead(BaseModel):
    case_id: str
    left_artifact_id: UUID
    right_artifact_id: UUID
    evaluator_kind: str
    left_evaluator_result_id: UUID | None
    right_evaluator_result_id: UUID | None
    left_implementation_version: str | None
    right_implementation_version: str | None
    left_config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    right_config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    left_dataset_version_id: UUID | None
    right_dataset_version_id: UUID | None
