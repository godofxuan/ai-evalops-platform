import asyncio
import contextlib
import os
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter_ns
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.lease import LeasePolicy
from app.persistence.database import (
    AsyncSessionFactory,
    create_database_engine,
    create_session_factory,
)
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    AuditEvent,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProgressEventOutbox,
    Tenant,
    TenantSchedulerState,
)
from tests.postgres_test_support import install_postgres_test_timeouts, wait_for_lock_sensitive


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


@dataclass(frozen=True, slots=True)
class FairnessFixture:
    tenant_id: UUID
    run_id: UUID
    api_key_id: UUID
    dataset_id: UUID
    version_id: UUID
    artifact_id: UUID
    digest: str
    job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class TraceEvent:
    sequence: int
    monotonic_ns: int
    worker_id: str
    stage: str
    tenant_id: UUID | None = None
    job_id: UUID | None = None


class CoordinatedFairRoundClaimer(SQLAlchemyJobClaimer):
    """Pause B's fair-round permit while all later A Workers reach selection."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        lease_policy: LeasePolicy,
        clock: FixedClock,
        paused_tenant_id: UUID,
    ) -> None:
        super().__init__(session_factory, lease_policy=lease_policy, clock=clock)
        self.paused_tenant_id = paused_tenant_id
        self.paused_tenant_locked = asyncio.Event()
        self.release_paused_permit = asyncio.Event()
        self.all_primary_contenders_selecting = asyncio.Event()
        self.trace: list[TraceEvent] = []
        self.receipts: list[ClaimedJob] = []
        self._primary_contenders: set[str] = set()
        self._worker_id: ContextVar[str] = ContextVar("durable_fairness_worker", default="unknown")
        self._paused_once = False

    def _record(
        self,
        stage: str,
        *,
        tenant_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> None:
        self.trace.append(
            TraceEvent(
                sequence=len(self.trace) + 1,
                monotonic_ns=perf_counter_ns(),
                worker_id=self._worker_id.get(),
                stage=stage,
                tenant_id=tenant_id,
                job_id=job_id,
            )
        )

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        token = self._worker_id.set(worker_id)
        try:
            claims = await super().claim(worker_id=worker_id, limit=limit)
            for claim in claims:
                self.receipts.append(claim)
                self._record(
                    "application_claim_receipt",
                    tenant_id=claim.tenant_id,
                    job_id=claim.job_id,
                )
            return claims
        finally:
            self._worker_id.reset(token)

    async def _before_scheduler_permit_select(self, *, worker_id: str) -> None:
        self._record("scheduler_permit_select")
        if worker_id.startswith("primary-") and worker_id != "primary-1":
            self._primary_contenders.add(worker_id)
            if len(self._primary_contenders) == 6:
                self.all_primary_contenders_selecting.set()

    async def _after_scheduler_permit_locked(
        self,
        *,
        worker_id: str,
        state: TenantSchedulerState,
    ) -> None:
        self._record("scheduler_permit_locked", tenant_id=state.tenant_id)
        if state.tenant_id == self.paused_tenant_id and not self._paused_once:
            self._paused_once = True
            self._record("scheduler_permit_paused", tenant_id=state.tenant_id)
            self.paused_tenant_locked.set()
            await self.release_paused_permit.wait()
            self._record("scheduler_permit_released", tenant_id=state.tenant_id)


class SimulatedPermitCrash(RuntimeError):
    pass


class CrashAfterPermitLockClaimer(SQLAlchemyJobClaimer):
    async def _after_scheduler_permit_locked(
        self,
        *,
        worker_id: str,
        state: TenantSchedulerState,
    ) -> None:
        raise SimulatedPermitCrash(f"simulated crash for {worker_id} tenant={state.tenant_id}")


async def _create_fairness_fixture(
    session_factory: AsyncSessionFactory,
    *,
    created_at: datetime,
    job_count: int,
) -> FairnessFixture:
    tenant_id = uuid4()
    fixture = FairnessFixture(
        tenant_id=tenant_id,
        run_id=uuid4(),
        api_key_id=uuid4(),
        dataset_id=uuid4(),
        version_id=uuid4(),
        artifact_id=uuid4(),
        digest=tenant_id.hex * 2,
        job_ids=tuple(uuid4() for _ in range(job_count)),
    )
    async with session_factory.begin() as session:
        session.add(
            Tenant(
                id=fixture.tenant_id,
                slug=f"durable-fairness-{fixture.tenant_id.hex}",
                name="Durable fairness concurrency test",
            )
        )
        await session.flush()
        session.add_all(
            [
                APIKey(
                    id=fixture.api_key_id,
                    tenant_id=fixture.tenant_id,
                    name="durable-fairness-test",
                    key_prefix=f"df_{fixture.tenant_id.hex[:12]}",
                    key_hash="not-a-real-key",
                ),
                Dataset(
                    id=fixture.dataset_id,
                    tenant_id=fixture.tenant_id,
                    name="durable-fairness-dataset",
                ),
                ArtifactBlob(
                    sha256=fixture.digest,
                    byte_size=1,
                    storage_path=f"{fixture.digest[:2]}/{fixture.digest}",
                ),
                ArtifactReference(
                    id=fixture.artifact_id,
                    tenant_id=fixture.tenant_id,
                    artifact_type=ArtifactType.DATASET_SOURCE,
                    blob_sha256=fixture.digest,
                    media_type="application/x-ndjson",
                ),
            ]
        )
        await session.flush()
        session.add(
            DatasetVersion(
                id=fixture.version_id,
                dataset_id=fixture.dataset_id,
                tenant_id=fixture.tenant_id,
                artifact_id=fixture.artifact_id,
                version=1,
                schema_version="1",
                sha256=fixture.digest,
                case_count=job_count,
            )
        )
        await session.flush()
        session.add(
            EvaluationRun(
                id=fixture.run_id,
                tenant_id=fixture.tenant_id,
                dataset_version_id=fixture.version_id,
                dataset_hash=fixture.digest,
                idempotency_key=f"durable-fairness-{fixture.run_id.hex}",
                request_hash=fixture.digest,
                target_type="mock",
                target_config_json={},
                target_config_hash=fixture.digest,
                evaluator_type="execution",
                evaluator_config_json={},
                evaluator_config_hash=fixture.digest,
                target_version="v1",
                evaluator_version="v1",
                status=RunStatus.RUNNING,
                total_jobs=job_count,
                created_by=fixture.api_key_id,
                created_at=created_at,
            )
        )
        await session.flush()
        session.add_all(
            [
                EvaluationJob(
                    id=job_id,
                    run_id=fixture.run_id,
                    case_id=f"job-{index}",
                    case_payload_json={"case_id": f"job-{index}"},
                    status=JobStatus.QUEUED,
                    priority=0,
                    max_attempts=3,
                    created_at=created_at + timedelta(microseconds=index),
                )
                for index, job_id in enumerate(fixture.job_ids, start=1)
            ]
        )
    return fixture


async def _delete_fairness_fixture(
    session_factory: AsyncSessionFactory,
    fixture: FairnessFixture,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            delete(ProgressEventOutbox).where(ProgressEventOutbox.run_id == fixture.run_id)
        )
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == fixture.tenant_id))
        await session.execute(delete(JobAttempt).where(JobAttempt.job_id.in_(fixture.job_ids)))
        await session.execute(delete(EvaluationJob).where(EvaluationJob.run_id == fixture.run_id))
        await session.execute(delete(EvaluationRun).where(EvaluationRun.id == fixture.run_id))
        await session.execute(delete(DatasetVersion).where(DatasetVersion.id == fixture.version_id))
        await session.execute(
            delete(ArtifactReference).where(ArtifactReference.id == fixture.artifact_id)
        )
        await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == fixture.digest))
        await session.execute(delete(Dataset).where(Dataset.id == fixture.dataset_id))
        await session.execute(delete(APIKey).where(APIKey.id == fixture.api_key_id))
        await session.execute(delete(Tenant).where(Tenant.id == fixture.tenant_id))


def _trace_payload(events: list[TraceEvent]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": event.sequence,
            "monotonic_ns": event.monotonic_ns,
            "worker_id": event.worker_id,
            "stage": event.stage,
            "tenant_id": str(event.tenant_id) if event.tenant_id is not None else None,
            "job_id": str(event.job_id) if event.job_id is not None else None,
        }
        for event in events
    ]


@pytest.mark.integration
async def test_fair_reservation_does_not_allow_secondary_durable_receipt_overtaking() -> None:
    """Candidate 3 GREEN: a pending B round member prevents any A2 admission."""

    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    primary = await _create_fairness_fixture(
        session_factory,
        created_at=now - timedelta(minutes=2),
        job_count=21,
    )
    secondary = await _create_fairness_fixture(
        session_factory,
        created_at=now - timedelta(minutes=1),
        job_count=1,
    )
    claimer = CoordinatedFairRoundClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
        paused_tenant_id=secondary.tenant_id,
    )
    ready = asyncio.Barrier(7)

    async def gated_primary_worker(index: int) -> tuple[ClaimedJob, ...]:
        await ready.wait()
        return await claimer.claim(worker_id=f"primary-{index + 2}", limit=1)

    primary_tasks: list[asyncio.Task[tuple[ClaimedJob, ...]]] = []
    secondary_task: asyncio.Task[tuple[ClaimedJob, ...]] | None = None
    try:
        first_primary = await wait_for_lock_sensitive(
            claimer.claim(worker_id="primary-1", limit=1),
            operation="Candidate 3 deterministic first primary receipt",
        )
        assert len(first_primary) == 1
        assert first_primary[0].tenant_id == primary.tenant_id
        first_sequence = first_primary[0].scheduler_claim_sequence
        assert first_sequence is not None

        secondary_task = asyncio.create_task(claimer.claim(worker_id="secondary-1", limit=1))
        await wait_for_lock_sensitive(
            claimer.paused_tenant_locked.wait(),
            operation="Candidate 3 secondary round permit lock",
        )

        primary_tasks = [asyncio.create_task(gated_primary_worker(index)) for index in range(6)]
        await ready.wait()
        await wait_for_lock_sensitive(
            claimer.all_primary_contenders_selecting.wait(),
            operation="Candidate 3 all later primary Workers reach permit selection",
        )

        # Every contender crossed the explicit selector hook while B still
        # holds its PENDING state row. The invariant, not a timing sleep,
        # prevents a later primary receipt before B.
        assert [claim.tenant_id for claim in claimer.receipts] == [primary.tenant_id]

        claimer.release_paused_permit.set()
        secondary_claims = await wait_for_lock_sensitive(
            secondary_task,
            operation="Candidate 3 delayed secondary durable claim",
        )
        assert len(secondary_claims) == 1
        assert secondary_claims[0].tenant_id == secondary.tenant_id
        assert secondary_claims[0].scheduler_claim_sequence == first_sequence + 1

        primary_batches = await wait_for_lock_sensitive(
            asyncio.gather(*primary_tasks),
            operation="Candidate 3 later primary claims after B round completion",
        )
        assert all(len(batch) == 1 for batch in primary_batches)
        assert all(batch[0].tenant_id == primary.tenant_id for batch in primary_batches)

        receipt_tenants = [claim.tenant_id for claim in claimer.receipts]
        secondary_position = receipt_tenants.index(secondary.tenant_id) + 1
        assert secondary_position <= 2, (
            "FAIR_RESERVATION_NOT_SUFFICIENT_RED: "
            f"secondary durable committed claim receipt position={secondary_position}; "
            f"trace={_trace_payload(claimer.trace)}"
        )
    finally:
        claimer.release_paused_permit.set()
        for task in primary_tasks:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if secondary_task is not None and not secondary_task.done():
            secondary_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await secondary_task
        await _delete_fairness_fixture(session_factory, secondary)
        await _delete_fairness_fixture(session_factory, primary)
        await engine.dispose()


@pytest.mark.integration
async def test_crash_after_permit_lock_rolls_back_permit_and_job_for_recovery() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    fixture = await _create_fairness_fixture(
        session_factory,
        created_at=now - timedelta(minutes=1),
        job_count=1,
    )
    crashing = CrashAfterPermitLockClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    recovery = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    try:
        with pytest.raises(SimulatedPermitCrash):
            await wait_for_lock_sensitive(
                crashing.claim(worker_id="permit-crash", limit=1),
                operation="Candidate 3 crash after per-Tenant permit lock",
            )

        async with session_factory() as session:
            state = await session.get(TenantSchedulerState, fixture.tenant_id)
            job = await session.get(EvaluationJob, fixture.job_ids[0])
            assert state is not None and state.status == "pending"
            assert job is not None
            assert job.status is JobStatus.QUEUED
            assert job.attempt_count == 0
            assert job.lease_owner is None
            assert job.lease_expires_at is None

        claims = await wait_for_lock_sensitive(
            recovery.claim(worker_id="permit-crash-recovery", limit=1),
            operation="Candidate 3 recovery consumes rolled-back permit",
        )
        assert [claim.job_id for claim in claims] == [fixture.job_ids[0]]
        assert claims[0].scheduler_claim_sequence is not None
    finally:
        await _delete_fairness_fixture(session_factory, fixture)
        await engine.dispose()


@pytest.mark.integration
async def test_locked_tenant_permit_does_not_block_other_tenant_progress() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    first = await _create_fairness_fixture(
        session_factory,
        created_at=now - timedelta(minutes=2),
        job_count=1,
    )
    second = await _create_fairness_fixture(
        session_factory,
        created_at=now - timedelta(minutes=1),
        job_count=1,
    )
    pausing = CoordinatedFairRoundClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
        paused_tenant_id=first.tenant_id,
    )
    progressing = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    paused_task: asyncio.Task[tuple[ClaimedJob, ...]] | None = None
    try:
        paused_task = asyncio.create_task(pausing.claim(worker_id="locked-first", limit=1))
        await wait_for_lock_sensitive(
            pausing.paused_tenant_locked.wait(),
            operation="Candidate 3 first Tenant permit lock",
        )

        other_claims = await wait_for_lock_sensitive(
            progressing.claim(worker_id="other-tenant", limit=1),
            operation="Candidate 3 other-Tenant SKIP LOCKED progress",
        )
        assert len(other_claims) == 1
        assert other_claims[0].tenant_id == second.tenant_id

        pausing.release_paused_permit.set()
        first_claims = await wait_for_lock_sensitive(
            paused_task,
            operation="Candidate 3 release first Tenant permit",
        )
        assert len(first_claims) == 1
        assert first_claims[0].tenant_id == first.tenant_id
    finally:
        pausing.release_paused_permit.set()
        if paused_task is not None and not paused_task.done():
            paused_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await paused_task
        await _delete_fairness_fixture(session_factory, second)
        await _delete_fairness_fixture(session_factory, first)
        await engine.dispose()
