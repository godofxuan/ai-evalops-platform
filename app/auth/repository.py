from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, or_, select, update
from sqlalchemy.sql import Select
from sqlalchemy.sql.dml import Update

from app.auth.service import APIKeyCandidate
from app.domain.enums import APIKeyStatus, TenantStatus
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import APIKey, Tenant


def build_find_candidate_statement(
    prefix: str,
) -> Select[tuple[APIKey, TenantStatus]]:
    return (
        select(APIKey, Tenant.status)
        .join(Tenant, Tenant.id == APIKey.tenant_id)
        .where(APIKey.key_prefix == prefix)
    )


def build_mark_used_statement(api_key_id: UUID, *, used_at: datetime) -> Update:
    active_tenant_exists = exists(
        select(1).where(
            Tenant.id == APIKey.tenant_id,
            Tenant.status == TenantStatus.ACTIVE,
        )
    )
    return (
        update(APIKey)
        .where(
            APIKey.id == api_key_id,
            APIKey.status == APIKeyStatus.ACTIVE,
            or_(APIKey.expires_at.is_(None), APIKey.expires_at > used_at),
            active_tenant_exists,
        )
        .values(last_used_at=used_at)
        .returning(APIKey.id)
    )


class SQLAlchemyAPIKeyLookup:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def find_by_prefix(self, prefix: str) -> APIKeyCandidate | None:
        async with self._session_factory() as session:
            result = await session.execute(build_find_candidate_statement(prefix))
            row = result.one_or_none()

        if row is None:
            return None
        api_key = row[0]
        tenant_status = row[1]
        return APIKeyCandidate(
            api_key_id=api_key.id,
            tenant_id=api_key.tenant_id,
            key_prefix=api_key.key_prefix,
            key_hash=api_key.key_hash,
            api_key_status=api_key.status,
            tenant_status=tenant_status,
            expires_at=api_key.expires_at,
            can_review=api_key.can_review,
            can_create_review_tasks=api_key.can_create_review_tasks,
        )

    async def mark_used(self, api_key_id: UUID, *, used_at: datetime) -> bool:
        async with self._session_factory.begin() as session:
            result = await session.execute(build_mark_used_statement(api_key_id, used_at=used_at))
            return result.scalar_one_or_none() is not None
