import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.jobs.claiming import (
    ClaimedJob,
    SQLAlchemyJobClaimer,
    build_tenant_job_claim_statement,
)
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
)
from tests.postgres_test_support import (
    install_postgres_test_timeouts,
    wait_for_lock_sensitive,
)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class InstrumentedClaimer(SQLAlchemyJobClaimer):
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        lease_policy: LeasePolicy,
        clock: FixedClock,
    ) -> None:
        super().__init__(session_factory, lease_policy=lease_policy, clock=clock)
        self.claim_attempts = 0
        self.empty_attempts = 0
        self.eligible_probes = 0
        self.empty_while_eligible = 0

    async def _claim_once(
        self,
        *,
        worker_id: str,
        limit: int,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        self.claim_attempts += 1
        claims = await super()._claim_once(
            worker_id=worker_id,
            limit=limit,
            eligible_at=eligible_at,
        )
        if not claims:
            self.empty_attempts += 1
        return claims

    async def _has_eligible_jobs(self, now: datetime) -> bool:
        self.eligible_probes += 1
        eligible = await super()._has_eligible_jobs(now)
        if eligible:
            self.empty_while_eligible += 1
        return eligible

    async def claim_reserved_for_diagnostic(
        self,
        *,
        worker_id: str,
        tenant_id: UUID,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        return await self._claim_reserved_tenant(
            worker_id=worker_id,
            tenant_id=tenant_id,
            eligible_at=eligible_at,
        )


@dataclass(frozen=True, slots=True)
class ClaimFixture:
    tenant_id: UUID
    run_id: UUID
    api_key_id: UUID
    dataset_id: UUID
    version_id: UUID
    artifact_id: UUID
    digest: str
    job_ids: tuple[UUID, ...]


async def _create_claim_fixture(
    session_factory: AsyncSessionFactory,
    *,
    created_at: datetime,
    job_count: int = 4,
) -> ClaimFixture:
    tenant_id = uuid4()
    fixture = ClaimFixture(
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
                slug=f"parallel-{fixture.tenant_id.hex}",
                name="Tenant claim parallelism test",
            )
        )
        await session.flush()
        session.add_all(
            [
                APIKey(
                    id=fixture.api_key_id,
                    tenant_id=fixture.tenant_id,
                    name="parallel-claim-test",
                    key_prefix=f"cp_{fixture.tenant_id.hex[:12]}",
                    key_hash="not-a-real-key",
                ),
                Dataset(
                    id=fixture.dataset_id,
                    tenant_id=fixture.tenant_id,
                    name="parallel-claim-dataset",
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
                idempotency_key=f"parallel-{fixture.run_id.hex}",
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
                    max_attempts=3,
                    created_at=created_at + timedelta(microseconds=index),
                )
                for index, job_id in enumerate(fixture.job_ids, start=1)
            ]
        )
    return fixture


async def _delete_claim_fixture(
    session_factory: AsyncSessionFactory,
    fixture: ClaimFixture,
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


@pytest.mark.integration
async def test_worker_claims_next_job_while_same_tenant_head_claim_is_uncommitted() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
    claimer = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    outcomes: list[tuple[UUID, tuple[UUID, ...]]] = []
    try:
        for repetition in range(20):
            fixture = await _create_claim_fixture(
                session_factory,
                created_at=now + timedelta(minutes=repetition),
            )
            try:
                async with session_factory.begin() as worker_a_session:
                    worker_a_rows = (
                        await worker_a_session.execute(
                            build_tenant_job_claim_statement(
                                now=now,
                                tenant_id=fixture.tenant_id,
                            )
                        )
                    ).all()
                    assert [job.id for job, _run in worker_a_rows] == [fixture.job_ids[0]]

                    worker_b_claims = await wait_for_lock_sensitive(
                        claimer.claim(
                            worker_id=f"parallel-worker-b-{repetition}",
                            limit=1,
                        ),
                        operation="locked-head fallback claim",
                    )
                    outcomes.append(
                        (
                            fixture.job_ids[1],
                            tuple(claim.job_id for claim in worker_b_claims),
                        )
                    )
            finally:
                await _delete_claim_fixture(session_factory, fixture)
    finally:
        await engine.dispose()

    assert all(observed == (expected,) for expected, observed in outcomes), outcomes


@pytest.mark.integration
async def test_fair_selector_skips_locked_tenant_head_job() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    claimer = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    outcomes: list[tuple[UUID, tuple[UUID, ...]]] = []
    try:
        for repetition in range(20):
            fixture = await _create_claim_fixture(
                session_factory,
                created_at=now + timedelta(minutes=repetition),
            )
            try:
                async with session_factory.begin() as worker_a_session:
                    locked_job_id = await worker_a_session.scalar(
                        select(EvaluationJob.id)
                        .where(EvaluationJob.id == fixture.job_ids[0])
                        .with_for_update()
                    )
                    assert locked_job_id == fixture.job_ids[0]

                    worker_b_claims = await wait_for_lock_sensitive(
                        claimer.claim(
                            worker_id=f"rank-pruning-worker-b-{repetition}",
                            limit=1,
                        ),
                        operation="rank-pruning fallback claim",
                    )
                    outcomes.append(
                        (
                            fixture.job_ids[1],
                            tuple(claim.job_id for claim in worker_b_claims),
                        )
                    )
            finally:
                await _delete_claim_fixture(session_factory, fixture)
    finally:
        await engine.dispose()

    assert all(observed == (expected,) for expected, observed in outcomes), (
        f"RANK_PRUNING_CONCURRENCY_RED: {outcomes}"
    )


@pytest.mark.integration
async def test_job_claim_does_not_serialize_on_locked_tenant_row() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    claimer = InstrumentedClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    outcomes: list[tuple[UUID, tuple[UUID, ...]]] = []
    try:
        for repetition in range(20):
            fixture = await _create_claim_fixture(
                session_factory,
                created_at=now + timedelta(minutes=repetition),
            )
            try:
                async with session_factory.begin() as worker_a_session:
                    locked_tenant_id = await worker_a_session.scalar(
                        select(Tenant.id).where(Tenant.id == fixture.tenant_id).with_for_update()
                    )
                    assert locked_tenant_id == fixture.tenant_id

                    worker_b_claims = await wait_for_lock_sensitive(
                        claimer.claim_reserved_for_diagnostic(
                            worker_id=f"tenant-hot-row-worker-b-{repetition}",
                            tenant_id=fixture.tenant_id,
                            eligible_at=now,
                        ),
                        operation="durable claim under external Tenant FOR UPDATE",
                    )
                    outcomes.append(
                        (
                            fixture.job_ids[0],
                            tuple(claim.job_id for claim in worker_b_claims),
                        )
                    )
            finally:
                await _delete_claim_fixture(session_factory, fixture)
    finally:
        await engine.dispose()

    assert all(observed == (expected,) for expected, observed in outcomes), (
        f"TENANT_HOT_ROW_RED: {outcomes}"
    )


@pytest.mark.integration
async def test_same_tenant_eight_worker_contention_diagnostics() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 11, 0, tzinfo=UTC)
    fixture = await _create_claim_fixture(
        session_factory,
        created_at=now,
        job_count=100,
    )
    claimer = InstrumentedClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    barrier = asyncio.Barrier(9)

    async def claim_one(worker_number: int) -> tuple[tuple[ClaimedJob, ...], float]:
        await barrier.wait()
        started_at = perf_counter()
        claims = await claimer.claim(
            worker_id=f"diagnostic-worker-{worker_number}",
            limit=1,
        )
        return claims, (perf_counter() - started_at) * 1_000

    try:
        tasks = [asyncio.create_task(claim_one(worker_number)) for worker_number in range(8)]
        await barrier.wait()
        results = await wait_for_lock_sensitive(
            asyncio.gather(*tasks),
            operation="eight-worker same-tenant claim wave",
        )
    finally:
        await _delete_claim_fixture(session_factory, fixture)
        await engine.dispose()

    claimed_job_ids = [claim.job_id for claims, _latency in results for claim in claims]
    latencies_ms = sorted(latency for _claims, latency in results)
    successful_requests = sum(bool(claims) for claims, _latency in results)
    retries = claimer.claim_attempts - len(results)
    retry_per_success = retries / successful_requests if successful_requests else None
    diagnostics = {
        "claim_requests": len(results),
        "claim_attempts": claimer.claim_attempts,
        "successful_requests": successful_requests,
        "empty_requests": len(results) - successful_requests,
        "claimed_jobs": len(claimed_job_ids),
        "unique_claimed_jobs": len(set(claimed_job_ids)),
        "empty_attempts": claimer.empty_attempts,
        "eligible_probes": claimer.eligible_probes,
        "empty_while_eligible": claimer.empty_while_eligible,
        "contention_retries": retries,
        "retry_per_success": retry_per_success,
        "latency_ms": {
            "points": latencies_ms,
            "p50": median(latencies_ms),
            "max": max(latencies_ms),
        },
    }

    assert len(claimed_job_ids) == 8, json.dumps(diagnostics, sort_keys=True)
    assert len(set(claimed_job_ids)) == 8, json.dumps(diagnostics, sort_keys=True)
    assert retry_per_success is not None and retry_per_success <= 0.25, (
        "SAME_TENANT_CONTENTION_DIAGNOSTIC_RED: " + json.dumps(diagnostics, sort_keys=True)
    )
