"""Tenant-consistent inputs for an atomic pair of existing Run/Job records."""

import hashlib
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

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
    max_total_attempts: int = 20_000
    max_active_jobs: int = 4
    max_observation_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_observation_bytes is not None:
            if (
                type(self.max_observation_bytes) is not int
                or not 1 <= self.max_observation_bytes <= 256 * 1024 * 1024
                or not self.baseline.cases
                or not self.candidate.cases
            ):
                raise ValueError("experiment observation budget or case count is invalid")
            per_job = self.observation_bytes_per_job
            if per_job is None or per_job < 1:
                raise ValueError("experiment observation budget cannot cover both arms")
            for arm in (self.baseline, self.candidate):
                configured = arm.evaluator_config.get("max_observation_bytes_per_case")
                if (
                    arm.evaluator_type not in {"product_qa_v2", "product_agent_v2"}
                    or arm.evaluator_version != "product-v2"
                    or type(configured) is not int
                    or configured != per_job
                ):
                    raise ValueError("experiment observation budget is not enforced by evaluator")
        if type(self.max_active_jobs) is not int or not 1 <= self.max_active_jobs <= 64:
            raise ValueError("experiment active job window must be within [1, 64]")
        if type(self.max_total_attempts) is not int or not 1 <= self.max_total_attempts <= 200_000:
            raise ValueError("experiment attempt budget must be within [1, 200000]")
        if any(
            type(arm.max_attempts) is not int or not 1 <= arm.max_attempts <= 10
            for arm in (self.baseline, self.candidate)
        ):
            raise ValueError("experiment per-job attempt budget must be within [1, 10]")
        if self.reserved_target_attempts > self.max_total_attempts:
            raise ValueError("experiment attempt budget cannot cover both arms and retries")
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

    @property
    def observation_bytes_per_job(self) -> int | None:
        if self.max_observation_bytes is None:
            return None
        return self.max_observation_bytes // (len(self.baseline.cases) + len(self.candidate.cases))

    @property
    def reserved_target_attempts(self) -> int:
        return sum(len(arm.cases) * arm.max_attempts for arm in (self.baseline, self.candidate))

    def snapshot_with_attempt_budget(self) -> dict[str, Any]:
        snapshot = deepcopy(self.snapshot)
        snapshot.pop("content_sha256", None)
        snapshot["attempt_budget"] = {
            "schema_version": "evalops.static-attempt-budget/1.0",
            "max_total_attempts": self.max_total_attempts,
            "reserved_target_attempts": self.reserved_target_attempts,
            "enforcement": "EXISTING_PER_JOB_ATTEMPT_LIMITS",
            "model_internal_calls_bounded": False,
            "hard_currency_budget": False,
        }
        snapshot["admission_budget"] = {
            "max_active_jobs": self.max_active_jobs,
            "scope": "BOTH_ARMS_AND_RETRIES",
            "enforcement": "DATABASE_ACTIVE_CLAIMS",
            "physical_upstream_concurrency_guaranteed": False,
        }
        snapshot.pop("observation_budget", None)
        if self.max_observation_bytes is not None:
            per_job = self.observation_bytes_per_job
            assert per_job is not None
            snapshot["observation_budget"] = {
                "max_observation_bytes": self.max_observation_bytes,
                "max_bytes_per_job": per_job,
                "reserved_bytes": per_job * (len(self.baseline.cases) + len(self.candidate.cases)),
                "scope": "ACCEPTED_NORMALIZED_OBSERVATIONS",
                "enforcement": "STATIC_PER_JOB_EVALUATOR_LIMIT",
                "unused_bytes_reallocated": False,
                "database_storage_or_rss_limit": False,
            }
        snapshot["content_sha256"] = canonical_request_hash(snapshot)
        return snapshot


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
        # Capture nested inputs and rerun invariants before the first await.
        pending = replace(
            pending,
            baseline=deepcopy(pending.baseline),
            candidate=deepcopy(pending.candidate),
            snapshot=deepcopy(pending.snapshot),
        )
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
                experiment_id = uuid4()
                baseline = await insert_run_and_jobs(
                    session,
                    replace(
                        pending.baseline,
                        idempotency_key=f"product:{key_digest}:baseline",
                        product_experiment_id=experiment_id,
                    ),
                )
                candidate = await insert_run_and_jobs(
                    session,
                    replace(
                        pending.candidate,
                        idempotency_key=f"product:{key_digest}:candidate",
                        product_experiment_id=experiment_id,
                    ),
                )
                row = ProductExperiment(
                    id=experiment_id,
                    max_active_jobs=pending.max_active_jobs,
                    tenant_id=pending.tenant_id,
                    created_by=pending.created_by,
                    idempotency_key=pending.idempotency_key,
                    request_hash=pending.request_hash,
                    snapshot_json=pending.snapshot_with_attempt_budget(),
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
