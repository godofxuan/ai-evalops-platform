from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class EventType(StrEnum):
    SNAPSHOT = "snapshot"
    RUN_STARTED = "run_started"
    JOB_PROGRESS = "job_progress"
    JOB_FAILED = "job_failed"
    JOB_RETRIED = "job_retried"
    RUN_COMPLETED = "run_completed"
    HEARTBEAT = "heartbeat"


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    run_id: UUID
    tenant_id: UUID
    timestamp: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


def run_event_channel(*, tenant_id: UUID, run_id: UUID) -> str:
    return f"evalops:{tenant_id}:run:{run_id}"
