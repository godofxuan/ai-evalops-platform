from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.auth.api_keys import hash_api_key
from app.auth.service import APIKeyCandidate, InvalidAPIKeyError, authenticate_api_key
from app.domain.enums import APIKeyStatus, TenantStatus


class InMemoryAPIKeyLookup:
    def __init__(
        self,
        candidate: APIKeyCandidate,
        *,
        accept_mark_used: bool = True,
    ) -> None:
        self._candidate = candidate
        self._accept_mark_used = accept_mark_used
        self.last_used: tuple[UUID, datetime] | None = None

    async def find_by_prefix(self, prefix: str) -> APIKeyCandidate | None:
        if prefix == self._candidate.key_prefix:
            return self._candidate
        return None

    async def mark_used(self, api_key_id: UUID, *, used_at: datetime) -> bool:
        if not self._accept_mark_used:
            return False
        self.last_used = (api_key_id, used_at)
        return True


async def test_valid_api_key_returns_server_derived_principal_and_marks_last_used() -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    plaintext = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    api_key_id = UUID("00000000-0000-0000-0000-000000000101")
    tenant_id = UUID("00000000-0000-0000-0000-000000000201")
    candidate = APIKeyCandidate(
        api_key_id=api_key_id,
        tenant_id=tenant_id,
        key_prefix="evk_001122334455",
        key_hash=hash_api_key(plaintext, salt=bytes(range(16))),
        api_key_status=APIKeyStatus.ACTIVE,
        tenant_status=TenantStatus.ACTIVE,
        expires_at=None,
        can_review=True,
    )
    lookup = InMemoryAPIKeyLookup(candidate)

    principal = await authenticate_api_key(plaintext, lookup=lookup, now=now)

    assert principal.tenant_id == tenant_id
    assert principal.api_key_id == api_key_id
    assert principal.key_prefix == "evk_001122334455"
    assert principal.can_review is True
    assert lookup.last_used == (api_key_id, now)


async def test_revoked_api_key_is_rejected_without_marking_last_used() -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    plaintext = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    candidate = APIKeyCandidate(
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        key_prefix="evk_001122334455",
        key_hash=hash_api_key(plaintext, salt=bytes(range(16))),
        api_key_status=APIKeyStatus.REVOKED,
        tenant_status=TenantStatus.ACTIVE,
        expires_at=None,
    )
    lookup = InMemoryAPIKeyLookup(candidate)

    with pytest.raises(InvalidAPIKeyError):
        await authenticate_api_key(plaintext, lookup=lookup, now=now)

    assert lookup.last_used is None


async def test_expired_api_key_is_rejected_without_marking_last_used() -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    plaintext = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    candidate = APIKeyCandidate(
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        key_prefix="evk_001122334455",
        key_hash=hash_api_key(plaintext, salt=bytes(range(16))),
        api_key_status=APIKeyStatus.ACTIVE,
        tenant_status=TenantStatus.ACTIVE,
        expires_at=now,
    )
    lookup = InMemoryAPIKeyLookup(candidate)

    with pytest.raises(InvalidAPIKeyError):
        await authenticate_api_key(plaintext, lookup=lookup, now=now)

    assert lookup.last_used is None


async def test_disabled_tenant_api_key_is_rejected_without_marking_last_used() -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    plaintext = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    candidate = APIKeyCandidate(
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        key_prefix="evk_001122334455",
        key_hash=hash_api_key(plaintext, salt=bytes(range(16))),
        api_key_status=APIKeyStatus.ACTIVE,
        tenant_status=TenantStatus.DISABLED,
        expires_at=None,
    )
    lookup = InMemoryAPIKeyLookup(candidate)

    with pytest.raises(InvalidAPIKeyError):
        await authenticate_api_key(plaintext, lookup=lookup, now=now)

    assert lookup.last_used is None


async def test_api_key_is_rejected_when_final_state_confirmation_loses_race() -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    plaintext = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    candidate = APIKeyCandidate(
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        key_prefix="evk_001122334455",
        key_hash=hash_api_key(plaintext, salt=bytes(range(16))),
        api_key_status=APIKeyStatus.ACTIVE,
        tenant_status=TenantStatus.ACTIVE,
        expires_at=None,
    )
    lookup = InMemoryAPIKeyLookup(candidate, accept_mark_used=False)

    with pytest.raises(InvalidAPIKeyError):
        await authenticate_api_key(plaintext, lookup=lookup, now=now)

    assert lookup.last_used is None
