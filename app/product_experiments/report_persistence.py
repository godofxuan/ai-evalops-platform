"""Publish a single immutable experiment report through the existing artifact lifecycle."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.artifacts.repository import ensure_artifact_reference
from app.artifacts.storage import StoredArtifact
from app.auth.principals import Principal
from app.domain.enums import ArtifactType, RunStatus
from app.jobs.cancellation import build_tenant_key_share_for_cancellation_statement
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import EvaluationRun, ProductExperiment
from app.product_experiments.result_snapshot import ResultSnapshotIntegrityError
from app.runs.idempotency import canonical_request_hash
from app.runs.service import RunNotFoundError


class ReportPublicationConflictError(ValueError):
    """A published report cannot be overwritten by a different result or algorithm output."""


@dataclass(frozen=True, slots=True)
class PublishedProductReport:
    experiment_id: UUID
    tenant_id: UUID
    baseline_run_id: UUID
    artifact_reference_id: UUID
    content_sha256: str
    snapshot_sha256: str


def _published(row: ProductExperiment) -> PublishedProductReport | None:
    if row.report_artifact_reference_id is None:
        if row.report_sha256 is not None or row.report_snapshot_sha256 is not None:
            raise ResultSnapshotIntegrityError("report publication metadata is incomplete")
        return None
    if row.report_sha256 is None or row.report_snapshot_sha256 is None:
        raise ResultSnapshotIntegrityError("report publication metadata is incomplete")
    return PublishedProductReport(
        row.id,
        row.tenant_id,
        row.baseline_run_id,
        row.report_artifact_reference_id,
        row.report_sha256,
        row.report_snapshot_sha256,
    )


class SQLAlchemyProductReportRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def get(self, *, tenant_id: UUID, experiment_id: UUID) -> PublishedProductReport | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ProductExperiment).where(
                    ProductExperiment.id == experiment_id,
                    ProductExperiment.tenant_id == tenant_id,
                )
            )
            return None if row is None else _published(row)

    async def publish(
        self, *, principal: Principal, snapshot: dict[str, Any], stored: StoredArtifact
    ) -> PublishedProductReport:
        snapshot = deepcopy(snapshot)
        unsigned = dict(snapshot)
        digest = unsigned.pop("content_sha256", None)
        if (
            snapshot.get("schema_version") != "evalops.durable-result-snapshot/1.0"
            or snapshot.get("tenant_id") != str(principal.tenant_id)
            or digest != canonical_request_hash(unsigned)
        ):
            raise ResultSnapshotIntegrityError("report snapshot identity mismatch")
        experiment_id = UUID(snapshot["experiment_id"])
        async with self._session_factory.begin() as session:
            tenant = await session.scalar(
                build_tenant_key_share_for_cancellation_statement(tenant_id=principal.tenant_id)
            )
            if tenant is None:
                raise RunNotFoundError
            row = await session.scalar(
                select(ProductExperiment)
                .where(
                    ProductExperiment.id == experiment_id,
                    ProductExperiment.tenant_id == principal.tenant_id,
                )
                .with_for_update()
            )
            if row is None:
                raise RunNotFoundError
            existing = _published(row)
            if existing is not None:
                if existing.content_sha256 != stored.sha256 or existing.snapshot_sha256 != digest:
                    raise ReportPublicationConflictError(
                        "a different immutable report is already published"
                    )
                return existing
            if row.request_hash != snapshot["request_sha256"] or canonical_request_hash(
                row.snapshot_json
            ) != canonical_request_hash(snapshot["input_snapshot"]):
                raise ResultSnapshotIntegrityError("experiment input changed before publication")
            run_ids = (row.baseline_run_id, row.candidate_run_id)
            runs = {
                run.id: run
                for run in (
                    await session.scalars(
                        select(EvaluationRun)
                        .where(
                            EvaluationRun.id.in_(run_ids),
                            EvaluationRun.tenant_id == principal.tenant_id,
                        )
                        .order_by(EvaluationRun.id)
                        .with_for_update()
                    )
                ).all()
            }
            if len(runs) != 2:
                raise ResultSnapshotIntegrityError("experiment runs are missing")
            terminal = {
                RunStatus.SUCCEEDED,
                RunStatus.PARTIALLY_SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }
            for label, run_id in zip(("baseline", "candidate"), run_ids, strict=True):
                expected = snapshot["arms"][label]
                run = runs[run_id]
                if (
                    expected["run_id"] != str(run.id)
                    or run.product_experiment_id != row.id
                    or run.version != expected["run_version"]
                    or run.status not in terminal
                    or run.status.value != expected["run_status"]
                ):
                    raise ResultSnapshotIntegrityError("terminal run changed before publication")
            reference = await ensure_artifact_reference(
                session,
                tenant_id=principal.tenant_id,
                run_id=row.baseline_run_id,
                artifact_type=ArtifactType.PRODUCT_EXPERIMENT_REPORT,
                media_type="application/vnd.evalops.durable-experiment-report+json",
                stored=stored,
            )
            row.report_artifact_reference_id = reference.id
            row.report_sha256 = stored.sha256
            row.report_snapshot_sha256 = digest
            row.version += 1
            await session.flush()
            published = _published(row)
            assert published is not None
            return published
