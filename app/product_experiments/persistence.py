"""Tenant-consistent inputs for an atomic pair of existing Run/Job records."""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.principals import Principal
from app.core.clock import SystemClock
from app.jobs.cancellation import (
    build_tenant_key_share_for_cancellation_statement,
    cancel_run_in_session,
)
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import EvaluationRun, ProductExperiment
from app.runs.idempotency import canonical_request_hash
from app.runs.repository import NewRun, insert_run_and_jobs
from app.runs.service import IdempotencyConflictError


@dataclass(frozen=True, slots=True)
class NewProductExperiment:
    tenant_id: UUID
    created_by: UUID
    idempotency_key: str
    request_hash: str
    snapshot: dict[str, Any]
    baseline: NewRun
    candidate: NewRun

    def __post_init__(self) -> None:
        if any(arm.tenant_id != self.tenant_id for arm in (self.baseline, self.candidate)):
            raise ValueError("experiment arms must share the owning tenant")
        if any(arm.created_by != self.created_by for arm in (self.baseline, self.candidate)):
            raise ValueError("experiment arms must share the submitting actor")
        if (
            self.baseline.dataset_version_id != self.candidate.dataset_version_id
            or self.baseline.dataset_hash != self.candidate.dataset_hash
        ):
            raise ValueError("experiment arms must share the frozen dataset")
        if canonical_request_hash({"cases": self.baseline.cases}) != canonical_request_hash(
            {"cases": self.candidate.cases}
        ):
            raise ValueError("experiment arms must share identical ordered cases")
        if (
            self.baseline.evaluator_type != self.candidate.evaluator_type
            or self.baseline.evaluator_version != self.candidate.evaluator_version
            or canonical_request_hash(self.baseline.evaluator_config)
            != canonical_request_hash(self.candidate.evaluator_config)
        ):
            raise ValueError("experiment arms must share the evaluator and scoring policy")
        if self.baseline.execution_deadline_at != self.candidate.execution_deadline_at:
            raise ValueError("experiment arms must share the absolute deadline")


@dataclass(frozen=True, slots=True)
class ProductExperimentSnapshot:
    id: UUID
    tenant_id: UUID
    request_hash: str
    baseline_run_id: UUID
    candidate_run_id: UUID
    snapshot: dict[str, Any]
    cancel_requested: bool
    created_at: datetime


def _snapshot(row: ProductExperiment) -> ProductExperimentSnapshot:
    return ProductExperimentSnapshot(
        id=row.id,
        tenant_id=row.tenant_id,
        request_hash=row.request_hash,
        baseline_run_id=row.baseline_run_id,
        candidate_run_id=row.candidate_run_id,
        snapshot=dict(row.snapshot_json),
        cancel_requested=row.cancel_requested,
        created_at=row.created_at,
    )


class SQLAlchemyProductExperimentRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def cancel(
        self, *, principal: Principal, experiment_id: UUID
    ) -> ProductExperimentSnapshot | None:
        now = SystemClock().now()
        async with self._session_factory.begin() as session:
            statement = select(ProductExperiment).where(
                ProductExperiment.tenant_id == principal.tenant_id,
                ProductExperiment.id == experiment_id,
            )
            if (await session.execute(statement)).scalar_one_or_none() is None:
                return None
            await session.scalar(
                build_tenant_key_share_for_cancellation_statement(tenant_id=principal.tenant_id)
            )
            row = (
                await session.execute(
                    statement.with_for_update(of=ProductExperiment).execution_options(
                        populate_existing=True
                    )
                )
            ).scalar_one()
            run_ids = sorted((row.baseline_run_id, row.candidate_run_id))
            # Global order: Tenant → Experiment → Runs ordered by ID → Jobs.
            await session.execute(
                select(EvaluationRun)
                .where(
                    EvaluationRun.tenant_id == principal.tenant_id,
                    EvaluationRun.id.in_(run_ids),
                )
                .order_by(EvaluationRun.id)
                .with_for_update(of=EvaluationRun)
            )
            for run_id in run_ids:
                await cancel_run_in_session(session, principal=principal, run_id=run_id, now=now)
            if not row.cancel_requested:
                row.cancel_requested = True
                row.version += 1
            await session.flush()
            return _snapshot(row)

    async def get(
        self, *, tenant_id: UUID, experiment_id: UUID
    ) -> ProductExperimentSnapshot | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(ProductExperiment).where(
                        ProductExperiment.tenant_id == tenant_id,
                        ProductExperiment.id == experiment_id,
                    )
                )
            ).scalar_one_or_none()
            return None if row is None else _snapshot(row)

    async def find_by_key(
        self, *, tenant_id: UUID, idempotency_key: str
    ) -> ProductExperimentSnapshot | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(ProductExperiment).where(
                        ProductExperiment.tenant_id == tenant_id,
                        ProductExperiment.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            return None if row is None else _snapshot(row)

    async def create_or_replay(self, pending: NewProductExperiment) -> ProductExperimentSnapshot:
        existing = await self.find_by_key(
            tenant_id=pending.tenant_id, idempotency_key=pending.idempotency_key
        )
        if existing is not None:
            if existing.request_hash != pending.request_hash:
                raise IdempotencyConflictError
            return existing
        key_digest = hashlib.sha256(
            f"{pending.tenant_id}:{pending.idempotency_key}".encode()
        ).hexdigest()
        try:
            async with self._session_factory.begin() as session:
                baseline = await insert_run_and_jobs(
                    session,
                    replace(pending.baseline, idempotency_key=f"product:{key_digest}:baseline"),
                )
                candidate = await insert_run_and_jobs(
                    session,
                    replace(pending.candidate, idempotency_key=f"product:{key_digest}:candidate"),
                )
                row = ProductExperiment(
                    tenant_id=pending.tenant_id,
                    created_by=pending.created_by,
                    idempotency_key=pending.idempotency_key,
                    request_hash=pending.request_hash,
                    snapshot_json=pending.snapshot,
                    baseline_run_id=baseline.id,
                    candidate_run_id=candidate.id,
                )
                session.add(row)
                await session.flush()
                result = _snapshot(row)
            return result
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint not in {
                "uq_product_experiments_tenant_key",
                "uq_evaluation_runs_tenant_id_idempotency_key",
            }:
                raise
            existing = await self.find_by_key(
                tenant_id=pending.tenant_id, idempotency_key=pending.idempotency_key
            )
            if existing is None:
                raise
            if existing.request_hash != pending.request_hash:
                raise IdempotencyConflictError from None
            return existing
