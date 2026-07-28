from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetCase(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    case_id: str
    question: str
    expected_answer: Any
    metadata: dict[str, Any]

    @field_validator("case_id", "question")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=5_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime


class DatasetVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    version: int
    schema_version: str
    sha256: str
    case_count: int
    artifact_id: UUID
    created_at: datetime
