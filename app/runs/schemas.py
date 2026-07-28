from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.enums import RunStatus

ComponentType = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]
ComponentVersion = Annotated[str, Field(min_length=1, max_length=128)]


class ComponentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: ComponentType
    config: dict[str, JsonValue] = Field(default_factory=dict)
    version: ComponentVersion = "1"


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: UUID
    target: ComponentSpec
    evaluator: ComponentSpec
    source_commit: str | None = Field(default=None, min_length=1, max_length=128)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_version_id: UUID
    status: RunStatus
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict[str, JsonValue] = Field(default_factory=dict)
