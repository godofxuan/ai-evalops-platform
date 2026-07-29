import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.auth.api_keys import extract_key_prefix, hash_api_key, verify_api_key
from app.auth.principals import Principal
from app.domain.enums import APIKeyStatus, TenantStatus

_DUMMY_HASH = hash_api_key("invalid-api-key", salt=bytes(16))


@dataclass(frozen=True, slots=True)
class APIKeyCandidate:
    api_key_id: UUID
    tenant_id: UUID
    key_prefix: str
    key_hash: str
    api_key_status: APIKeyStatus
    tenant_status: TenantStatus
    expires_at: datetime | None
    can_review: bool = False


class APIKeyLookup(Protocol):
    async def find_by_prefix(self, prefix: str) -> APIKeyCandidate | None:
        """Return the candidate key and tenant state for a safe prefix."""

    async def mark_used(self, api_key_id: UUID, *, used_at: datetime) -> bool:
        """Atomically confirm the key remains valid and persist its use."""


class InvalidAPIKeyError(Exception):
    """Represent every externally indistinguishable authentication failure."""


async def authenticate_api_key(
    plaintext: str,
    *,
    lookup: APIKeyLookup,
    now: datetime,
) -> Principal:
    prefix = extract_key_prefix(plaintext)
    candidate = await lookup.find_by_prefix(prefix) if prefix is not None else None
    encoded_hash = candidate.key_hash if candidate is not None else _DUMMY_HASH
    hash_matches = await asyncio.to_thread(verify_api_key, plaintext, encoded_hash)

    if (
        candidate is None
        or not hash_matches
        or candidate.api_key_status is not APIKeyStatus.ACTIVE
        or (candidate.expires_at is not None and candidate.expires_at <= now)
        or candidate.tenant_status is not TenantStatus.ACTIVE
    ):
        raise InvalidAPIKeyError

    if not await lookup.mark_used(candidate.api_key_id, used_at=now):
        raise InvalidAPIKeyError

    return Principal(
        tenant_id=candidate.tenant_id,
        api_key_id=candidate.api_key_id,
        key_prefix=candidate.key_prefix,
        can_review=candidate.can_review,
    )
