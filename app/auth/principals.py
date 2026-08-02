from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: UUID
    api_key_id: UUID
    key_prefix: str
    can_review: bool = False
    can_create_review_tasks: bool = False
