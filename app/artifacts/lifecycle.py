from enum import StrEnum


class ArtifactBlobStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"
    DELETE_FAILED = "DELETE_FAILED"
    RESTORE_REQUIRED = "RESTORE_REQUIRED"


class ArtifactLifecycleConflictError(RuntimeError):
    """The blob cannot accept a reference in its current lifecycle state."""
