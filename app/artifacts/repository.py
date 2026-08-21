from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.artifacts.lifecycle import (
    ArtifactBlobStatus,
    ArtifactLifecycleConflictError,
)
from app.artifacts.service import (
    ArtifactReferenceLocation,
    DeletedArtifactReference,
)
from app.artifacts.storage import StoredArtifact
from app.domain.enums import ArtifactType
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import ArtifactBlob, ArtifactReference


class ArtifactMetadataIntegrityError(RuntimeError):
    """Database metadata conflicts with a server-derived content address."""


class SQLAlchemyArtifactReferenceGateway:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def get_location(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> ArtifactReferenceLocation | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    build_get_artifact_reference_statement(
                        tenant_id=tenant_id,
                        reference_id=reference_id,
                        run_id=run_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        reference, blob = row
        return ArtifactReferenceLocation(
            reference_id=reference.id,
            blob_sha256=blob.sha256,
        )

    async def delete_reference(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> DeletedArtifactReference | None:
        deletion_token: UUID | None = None
        async with self._session_factory.begin() as session:
            statement = select(ArtifactReference).where(
                ArtifactReference.id == reference_id,
                ArtifactReference.tenant_id == tenant_id,
                (
                    ArtifactReference.run_id.is_(None)
                    if run_id is None
                    else ArtifactReference.run_id == run_id
                ),
            )
            reference = (await session.execute(statement.with_for_update())).scalar_one_or_none()
            if reference is None:
                return None
            blob = (
                await session.execute(
                    select(ArtifactBlob)
                    .where(ArtifactBlob.sha256 == reference.blob_sha256)
                    .with_for_update()
                )
            ).scalar_one()
            blob_sha256 = reference.blob_sha256
            await session.delete(reference)
            await session.flush()
            remaining = bool(
                await session.scalar(
                    select(exists().where(ArtifactReference.blob_sha256 == blob_sha256))
                )
            )
            if not remaining:
                deletion_token = uuid4()
                blob.lifecycle_status = ArtifactBlobStatus.DELETE_PENDING
                blob.deletion_token = deletion_token
                blob.deletion_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
                blob.delete_attempt_count += 1
                blob.deletion_error_code = None
        return DeletedArtifactReference(
            blob_sha256=blob_sha256,
            last_reference=deletion_token is not None,
            deletion_token=deletion_token,
        )

    async def finalize_blob_deletion(
        self,
        *,
        sha256: str,
        deletion_token: UUID,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        async with self._session_factory.begin() as session:
            blob = (
                await session.execute(
                    select(ArtifactBlob).where(ArtifactBlob.sha256 == sha256).with_for_update()
                )
            ).scalar_one_or_none()
            if blob is None or blob.deletion_token != deletion_token:
                return
            referenced = bool(
                await session.scalar(
                    select(exists().where(ArtifactReference.blob_sha256 == sha256))
                )
            )
            if referenced:
                blob.lifecycle_status = ArtifactBlobStatus.RESTORE_REQUIRED
                blob.deletion_error_code = "reference_created_after_delete_claim"
            elif succeeded:
                blob.lifecycle_status = ArtifactBlobStatus.DELETED
                blob.deleted_at = datetime.now(UTC)
                blob.deletion_error_code = None
            else:
                blob.lifecycle_status = ArtifactBlobStatus.DELETE_FAILED
                blob.deletion_error_code = error_code or "artifact_delete_failed"
            blob.deletion_lease_expires_at = None

    async def claim_unreferenced_blob(self, *, sha256: str) -> bool:
        async with self._session_factory.begin() as session:
            referenced = bool(
                await session.scalar(
                    select(
                        exists(
                            select(ArtifactReference.id).where(
                                ArtifactReference.blob_sha256 == sha256
                            )
                        )
                    )
                )
            )
            if referenced:
                return False
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == sha256))
        return True


def build_get_artifact_reference_statement(
    *,
    tenant_id: UUID,
    reference_id: UUID,
    run_id: UUID | None = None,
) -> Select[tuple[ArtifactReference, ArtifactBlob]]:
    statement = (
        select(ArtifactReference, ArtifactBlob)
        .join(
            ArtifactBlob,
            ArtifactBlob.sha256 == ArtifactReference.blob_sha256,
        )
        .where(
            ArtifactReference.id == reference_id,
            ArtifactReference.tenant_id == tenant_id,
            (
                ArtifactReference.run_id.is_(None)
                if run_id is None
                else ArtifactReference.run_id == run_id
            ),
        )
    )
    return statement


async def ensure_artifact_reference(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    artifact_type: ArtifactType,
    media_type: str,
    stored: StoredArtifact,
    run_id: UUID | None = None,
) -> ArtifactReference:
    if (artifact_type is ArtifactType.DATASET_SOURCE) != (run_id is None):
        raise ArtifactMetadataIntegrityError(
            "artifact type and Run ownership scope are inconsistent"
        )
    await _ensure_artifact_blob(session, stored=stored)

    reference_id = uuid4()
    values = {
        "id": reference_id,
        "blob_sha256": stored.sha256,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "artifact_type": artifact_type,
        "media_type": media_type,
    }
    if run_id is None:
        reference = ArtifactReference(**values)
        session.add(reference)
        await session.flush()
        return reference

    inserted_id = await session.scalar(
        postgresql_insert(ArtifactReference)
        .values(**values)
        .on_conflict_do_nothing(
            constraint="uq_artifact_references_owner_type_blob",
        )
        .returning(ArtifactReference.id)
    )
    predicate = (
        ArtifactReference.id == inserted_id
        if inserted_id is not None
        else (
            (ArtifactReference.tenant_id == tenant_id)
            & (ArtifactReference.run_id == run_id)
            & (ArtifactReference.artifact_type == artifact_type)
            & (ArtifactReference.blob_sha256 == stored.sha256)
        )
    )
    reference = (await session.execute(select(ArtifactReference).where(predicate))).scalar_one()
    if reference.media_type != media_type:
        raise ArtifactMetadataIntegrityError(
            "artifact reference media type conflicts with existing ownership metadata"
        )
    return reference


async def _ensure_artifact_blob(
    session: AsyncSession,
    *,
    stored: StoredArtifact,
) -> ArtifactBlob:
    await session.execute(
        postgresql_insert(ArtifactBlob)
        .values(
            sha256=stored.sha256,
            byte_size=stored.size_bytes,
            storage_path=stored.relative_path.as_posix(),
        )
        .on_conflict_do_nothing(index_elements=[ArtifactBlob.sha256])
    )
    blob = (
        await session.execute(
            select(ArtifactBlob).where(ArtifactBlob.sha256 == stored.sha256).with_for_update()
        )
    ).scalar_one()
    if blob.lifecycle_status != ArtifactBlobStatus.ACTIVE:
        raise ArtifactLifecycleConflictError(
            f"artifact blob is not referenceable: {blob.lifecycle_status}"
        )
    if blob.byte_size != stored.size_bytes or blob.storage_path != stored.relative_path.as_posix():
        raise ArtifactMetadataIntegrityError(
            "artifact blob metadata conflicts with its content address"
        )
    return blob
