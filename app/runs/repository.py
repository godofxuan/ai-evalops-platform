from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select

from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    Artifact,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
)


@dataclass(frozen=True, slots=True)
class DatasetVersionSource:
    dataset_version_id: UUID
    sha256: str
    case_count: int


@dataclass(frozen=True, slots=True)
class NewRun:
    tenant_id: UUID
    created_by: UUID
    dataset_version_id: UUID
    dataset_hash: str
    idempotency_key: str
    request_hash: str
    target_type: str
    target_config: dict[str, Any]
    target_config_hash: str
    evaluator_config: dict[str, Any]
    evaluator_config_hash: str
    target_version: str
    evaluator_version: str
    source_commit: str | None
    max_attempts: int
    cases: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    id: UUID
    dataset_version_id: UUID
    request_hash: str
    status: RunStatus
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunRepository(Protocol):
    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> RunSnapshot | None:
        """Find a tenant-scoped prior request."""

    async def get_dataset_version_source(
        self,
        *,
        tenant_id: UUID,
        dataset_version_id: UUID,
    ) -> DatasetVersionSource | None:
        """Resolve a dataset version only through its tenant."""

    async def create_or_replay(self, new_run: NewRun) -> RunSnapshot:
        """Atomically create a Run and Jobs, or return a concurrent replay."""

    async def get_run(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> RunSnapshot | None:
        """Return a tenant-owned Run snapshot."""


def build_find_run_by_idempotency_statement(
    tenant_id: UUID,
    idempotency_key: str,
) -> Select[tuple[EvaluationRun]]:
    return select(EvaluationRun).where(
        EvaluationRun.tenant_id == tenant_id,
        EvaluationRun.idempotency_key == idempotency_key,
    )


def build_get_run_statement(
    tenant_id: UUID,
    run_id: UUID,
) -> Select[tuple[EvaluationRun]]:
    return select(EvaluationRun).where(
        EvaluationRun.id == run_id,
        EvaluationRun.tenant_id == tenant_id,
    )


def build_get_dataset_version_source_statement(
    tenant_id: UUID,
    dataset_version_id: UUID,
) -> Select[tuple[UUID, str, int]]:
    return (
        select(
            DatasetVersion.id,
            Artifact.sha256,
            DatasetVersion.case_count,
        )
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .join(Artifact, Artifact.id == DatasetVersion.artifact_id)
        .where(
            DatasetVersion.id == dataset_version_id,
            Dataset.tenant_id == tenant_id,
            Artifact.tenant_id == tenant_id,
            Artifact.artifact_type == ArtifactType.DATASET_SOURCE,
        )
    )


class SQLAlchemyRunRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> RunSnapshot | None:
        async with self._session_factory() as session:
            run = (
                await session.execute(
                    build_find_run_by_idempotency_statement(tenant_id, idempotency_key)
                )
            ).scalar_one_or_none()
        return None if run is None else _snapshot(run)

    async def get_dataset_version_source(
        self,
        *,
        tenant_id: UUID,
        dataset_version_id: UUID,
    ) -> DatasetVersionSource | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    build_get_dataset_version_source_statement(
                        tenant_id,
                        dataset_version_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return DatasetVersionSource(
            dataset_version_id=row[0],
            sha256=row[1],
            case_count=row[2],
        )

    async def create_or_replay(self, new_run: NewRun) -> RunSnapshot:
        run = EvaluationRun(
            tenant_id=new_run.tenant_id,
            dataset_version_id=new_run.dataset_version_id,
            dataset_hash=new_run.dataset_hash,
            idempotency_key=new_run.idempotency_key,
            request_hash=new_run.request_hash,
            target_type=new_run.target_type,
            target_config_json=new_run.target_config,
            target_config_hash=new_run.target_config_hash,
            evaluator_config_json=new_run.evaluator_config,
            evaluator_config_hash=new_run.evaluator_config_hash,
            target_version=new_run.target_version,
            evaluator_version=new_run.evaluator_version,
            source_commit=new_run.source_commit,
            status=RunStatus.QUEUED,
            total_jobs=len(new_run.cases),
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            created_by=new_run.created_by,
            version=1,
        )
        try:
            async with self._session_factory.begin() as session:
                session.add(run)
                await session.flush()
                session.add_all(
                    [
                        EvaluationJob(
                            run_id=run.id,
                            case_id=str(case["case_id"]),
                            case_payload_json=case,
                            status=JobStatus.QUEUED,
                            priority=0,
                            attempt_count=0,
                            max_attempts=new_run.max_attempts,
                            version=1,
                        )
                        for case in new_run.cases
                    ]
                )
                await session.flush()
        except IntegrityError as error:
            if _constraint_name(error) != "uq_evaluation_runs_tenant_id_idempotency_key":
                raise
            existing = await self.find_by_idempotency_key(
                tenant_id=new_run.tenant_id,
                idempotency_key=new_run.idempotency_key,
            )
            if existing is None:
                raise
            return existing
        return _snapshot(run)

    async def get_run(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> RunSnapshot | None:
        async with self._session_factory() as session:
            run = (
                await session.execute(build_get_run_statement(tenant_id, run_id))
            ).scalar_one_or_none()
        return None if run is None else _snapshot(run)


def _snapshot(run: EvaluationRun) -> RunSnapshot:
    return RunSnapshot(
        id=run.id,
        dataset_version_id=run.dataset_version_id,
        request_hash=run.request_hash,
        status=run.status,
        total_jobs=run.total_jobs,
        succeeded_jobs=run.succeeded_jobs,
        failed_jobs=run.failed_jobs,
        cancelled_jobs=run.cancelled_jobs,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None
