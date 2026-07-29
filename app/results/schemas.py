from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import ArtifactType, JobStatus

MetricName = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
]


class CaseQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, min_length=1, max_length=2_048)
    status: JobStatus | None = None
    error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_]+$",
    )
    sort: Literal["case_id", "latency", "metric"] = "case_id"
    metric_name: MetricName | None = None
    direction: Literal["asc", "desc"] = "asc"

    @model_validator(mode="after")
    def validate_metric_sort(self) -> "CaseQuery":
        if self.sort == "metric" and self.metric_name is None:
            raise ValueError("metric_name is required when sort=metric")
        if self.sort != "metric" and self.metric_name is not None:
            raise ValueError("metric_name is only valid when sort=metric")
        return self


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    case_id: str
    status: JobStatus
    attempt_count: int
    error_code: str | None
    answer: JsonValue | None
    evidence: dict[str, JsonValue]
    metrics: dict[str, JsonValue]
    latency_ms: int | None
    finished_at: datetime | None


class CasePage(BaseModel):
    items: list[CaseRead]
    next_cursor: str | None


class DistributionRead(BaseModel):
    count: int
    mean: float | None
    p50: float | None
    p95: float | None


class MetricsRead(BaseModel):
    total_jobs: int
    completion_rate: float
    success_rate: float
    failure_rate: float
    cancellation_rate: float
    latency: DistributionRead
    evaluator_metrics: dict[str, DistributionRead]


class ChangedCaseRead(BaseModel):
    case_id: str
    metric_deltas: dict[str, float]
    latency_delta_ms: int | None


class RunComparisonRead(BaseModel):
    warning: str | None
    intersection_count: int
    left_only_count: int
    right_only_count: int
    left: MetricsRead
    right: MetricsRead
    metric_deltas: dict[str, float]
    only_left_failed: list[str]
    only_right_failed: list[str]
    changed_cases: list[ChangedCaseRead]


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    artifact_type: ArtifactType
    sha256: str
    media_type: str
    byte_size: int
    created_at: datetime
