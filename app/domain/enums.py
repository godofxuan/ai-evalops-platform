from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class APIKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ArtifactType(StrEnum):
    DATASET_SOURCE = "dataset_source"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
