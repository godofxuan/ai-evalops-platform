from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent_eval.schema import (
    AgentRunArtifact,
    ArtifactSchemaVersion,
    FrameworkName,
    OpaqueIdentifier,
)


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
