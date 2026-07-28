from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class APIKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ArtifactType(StrEnum):
    DATASET_SOURCE = "dataset_source"
