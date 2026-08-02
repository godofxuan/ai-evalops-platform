from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select

from app.artifacts.repository import (
    ArtifactMetadataIntegrityError,
    ensure_artifact_reference,
)
from app.artifacts.storage import ArtifactStore, StoredArtifact
from app.auth.principals import Principal
from app.datasets.schemas import DatasetCreate, DatasetRead, DatasetVersionRead
from app.datasets.validation import (
    DEFAULT_JSONL_VALIDATION_LIMITS,
    JSONLValidationLimits,
    validate_jsonl,
)
from app.domain.enums import ArtifactType
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import Dataset, DatasetVersion


class DatasetNotFoundError(Exception):
    """Hide both absent and cross-tenant datasets behind one outcome."""


class DatasetNameConflictError(Exception):
    """The tenant already has a dataset with the requested name."""


class DuplicateDatasetVersionError(Exception):
    """The dataset already contains a version with the uploaded content."""


def build_get_dataset_statement(
    tenant_id: UUID,
    dataset_id: UUID,
) -> Select[tuple[Dataset]]:
    return select(Dataset).where(
        Dataset.id == dataset_id,
        Dataset.tenant_id == tenant_id,
    )


def build_lock_dataset_statement(
    tenant_id: UUID,
    dataset_id: UUID,
) -> Select[tuple[Dataset]]:
    return build_get_dataset_statement(tenant_id, dataset_id).with_for_update()


def build_get_dataset_version_statement(
    tenant_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
) -> Select[tuple[DatasetVersion]]:
    return (
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(
            DatasetVersion.id == version_id,
            DatasetVersion.dataset_id == dataset_id,
            Dataset.tenant_id == tenant_id,
        )
    )


class DatasetService(Protocol):
    async def create_dataset(
        self,
        *,
        principal: Principal,
        request: DatasetCreate,
    ) -> DatasetRead:
        """Create tenant-owned dataset metadata."""

    async def get_dataset(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
    ) -> DatasetRead:
        """Return tenant-owned dataset metadata or hide its existence."""

    async def create_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        content: bytes,
        media_type: str,
    ) -> DatasetVersionRead:
        """Validate and persist an immutable tenant-owned dataset version."""

    async def get_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        version_id: UUID,
    ) -> DatasetVersionRead:
        """Return a version only through its tenant-owned dataset chain."""


class SQLAlchemyDatasetService:
    def __init__(
        self,
        *,
        session_factory: AsyncSessionFactory,
        artifact_store: ArtifactStore,
        validation_limits: JSONLValidationLimits = DEFAULT_JSONL_VALIDATION_LIMITS,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store
        self._validation_limits = validation_limits

    async def create_dataset(
        self,
        *,
        principal: Principal,
        request: DatasetCreate,
    ) -> DatasetRead:
        dataset = Dataset(
            tenant_id=principal.tenant_id,
            name=request.name,
            description=request.description,
        )
        try:
            async with self._session_factory.begin() as session:
                session.add(dataset)
                await session.flush()
        except IntegrityError as error:
            if _constraint_name(error) == "uq_datasets_tenant_id_name":
                raise DatasetNameConflictError from None
            raise
        return DatasetRead.model_validate(dataset)

    async def get_dataset(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
    ) -> DatasetRead:
        async with self._session_factory() as session:
            result = await session.execute(
                build_get_dataset_statement(principal.tenant_id, dataset_id)
            )
            dataset = result.scalar_one_or_none()
        if dataset is None:
            raise DatasetNotFoundError
        return DatasetRead.model_validate(dataset)

    async def create_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        content: bytes,
        media_type: str,
    ) -> DatasetVersionRead:
        validated = validate_jsonl(content, limits=self._validation_limits)
        await self._assert_dataset_access(
            tenant_id=principal.tenant_id,
            dataset_id=dataset_id,
        )
        stored = await self._artifact_store.put_bytes(validated.content)
        _assert_stored_artifact_matches_validation(stored, validated.sha256)

        async with self._session_factory.begin() as session:
            dataset_result = await session.execute(
                build_lock_dataset_statement(principal.tenant_id, dataset_id)
            )
            dataset = dataset_result.scalar_one_or_none()
            if dataset is None:
                raise DatasetNotFoundError

            duplicate_id = await session.scalar(
                select(DatasetVersion.id).where(
                    DatasetVersion.dataset_id == dataset_id,
                    DatasetVersion.sha256 == validated.sha256,
                )
            )
            if duplicate_id is not None:
                raise DuplicateDatasetVersionError

            artifact_reference = await ensure_artifact_reference(
                session,
                tenant_id=principal.tenant_id,
                artifact_type=ArtifactType.DATASET_SOURCE,
                media_type=media_type,
                stored=stored,
            )
            current_version = await session.scalar(
                select(func.coalesce(func.max(DatasetVersion.version), 0)).where(
                    DatasetVersion.dataset_id == dataset_id
                )
            )
            dataset_version = DatasetVersion(
                dataset_id=dataset_id,
                artifact_id=artifact_reference.id,
                version=int(current_version or 0) + 1,
                schema_version="1",
                sha256=validated.sha256,
                case_count=validated.case_count,
            )
            session.add(dataset_version)
            await session.flush()

        return DatasetVersionRead.model_validate(dataset_version)

    async def get_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        version_id: UUID,
    ) -> DatasetVersionRead:
        async with self._session_factory() as session:
            result = await session.execute(
                build_get_dataset_version_statement(
                    principal.tenant_id,
                    dataset_id,
                    version_id,
                )
            )
            dataset_version = result.scalar_one_or_none()
        if dataset_version is None:
            raise DatasetNotFoundError
        return DatasetVersionRead.model_validate(dataset_version)

    async def _assert_dataset_access(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(build_get_dataset_statement(tenant_id, dataset_id))
            if result.scalar_one_or_none() is None:
                raise DatasetNotFoundError


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _assert_stored_artifact_matches_validation(
    stored: StoredArtifact,
    expected_sha256: str,
) -> None:
    if stored.sha256 != expected_sha256:
        raise ArtifactMetadataIntegrityError
