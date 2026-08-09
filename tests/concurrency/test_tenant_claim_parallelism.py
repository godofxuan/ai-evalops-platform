import asyncio
import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median, quantiles
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.jobs.claiming import (
    ClaimedJob,
    SQLAlchemyJobClaimer,
    build_claim_candidates_statement,
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
    create_postgres_test_engine,
    install_postgres_test_timeouts,
    wait_for_lock_sensitive,
    wait_for_postgres_lock_snapshot,
    write_lock_diagnostic,
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
        self.waiting_fallbacks = 0

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

    async def _claim_once_waiting_for_turn(
        self,
        *,
        worker_id: str,
        limit: int,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        self.waiting_fallbacks += 1
        self.claim_attempts += 1
        claims = await super()._claim_once_waiting_for_turn(
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

    async def reserve_tenant_turn_for_diagnostic(self, *, eligible_at: datetime) -> UUID | None:
        return await self._reserve_tenant_turn(eligible_at=eligible_at)


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
async def test_job_selector_is_independent_of_tenant_scheduler_lock() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    selector_engine = create_postgres_test_engine(
        database_url,
        application_name="final-scheduler-selector-only",
    )
    selector_session_factory = create_session_factory(selector_engine)
    now = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    fixture = await _create_claim_fixture(session_factory, created_at=now)
    try:
        async with session_factory.begin() as worker_a_session:
            locked_tenant_id = await worker_a_session.scalar(
                select(Tenant.id).where(Tenant.id == fixture.tenant_id).with_for_update()
            )
            assert locked_tenant_id == fixture.tenant_id

            async with selector_session_factory.begin() as worker_b_session:
                rows = (
                    await wait_for_lock_sensitive(
                        worker_b_session.execute(
                            build_tenant_job_claim_statement(
                                now=now,
                                tenant_id=fixture.tenant_id,
                            )
                        ),
                        operation="Job-only selector under Tenant FOR UPDATE",
                    )
                ).all()
            assert [job.id for job, _run in rows] == [fixture.job_ids[0]]
    finally:
        await _delete_claim_fixture(session_factory, fixture)
        await selector_engine.dispose()
        await engine.dispose()


@pytest.mark.integration
async def test_external_tenant_for_update_exposes_fk_lock_diagnostic() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    fixture_engine = create_database_engine(settings)
    install_postgres_test_timeouts(fixture_engine)
    fixture_session_factory = create_session_factory(fixture_engine)
    application_name = "final-scheduler-durable-for-update"
    claim_engine = create_postgres_test_engine(database_url, application_name=application_name)
    claim_session_factory = create_session_factory(claim_engine)
    now = datetime(2026, 8, 9, 10, 15, tzinfo=UTC)
    claimer = InstrumentedClaimer(
        claim_session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    fixture = await _create_claim_fixture(fixture_session_factory, created_at=now)
    claim_task: asyncio.Task[tuple[ClaimedJob, ...]] | None = None
    try:
        async with fixture_session_factory.begin() as worker_a_session:
            locked_tenant_id = await worker_a_session.scalar(
                select(Tenant.id).where(Tenant.id == fixture.tenant_id).with_for_update()
            )
            assert locked_tenant_id == fixture.tenant_id

            claim_task = asyncio.create_task(
                claimer.claim_reserved_for_diagnostic(
                    worker_id="durable-for-update-worker",
                    tenant_id=fixture.tenant_id,
                    eligible_at=now,
                )
            )
            snapshot = await wait_for_postgres_lock_snapshot(
                database_url,
                target_application_name=application_name,
            )
            write_lock_diagnostic(
                {
                    "hypothesis": "H2_FK_LOCK_INTERACTION",
                    "test": "external_tenant_for_update",
                    "tenant_id": str(fixture.tenant_id),
                    "expected_outcome": "lock_timeout",
                    "snapshot": snapshot,
                }
            )

            with pytest.raises(DBAPIError) as captured:
                await wait_for_lock_sensitive(
                    claim_task,
                    operation="durable claim under external Tenant FOR UPDATE",
                )
            assert getattr(captured.value.orig, "sqlstate", None) == "55P03"
    finally:
        if claim_task is not None and not claim_task.done():
            claim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await claim_task
        await _delete_claim_fixture(fixture_session_factory, fixture)
        await claim_engine.dispose()
        await fixture_engine.dispose()


@pytest.mark.integration
async def test_external_tenant_no_key_update_allows_full_durable_claim() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    fixture_engine = create_database_engine(settings)
    install_postgres_test_timeouts(fixture_engine)
    fixture_session_factory = create_session_factory(fixture_engine)
    claim_engine = create_postgres_test_engine(
        database_url,
        application_name="final-scheduler-durable-no-key-update",
    )
    claim_session_factory = create_session_factory(claim_engine)
    now = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)
    claimer = InstrumentedClaimer(
        claim_session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    fixture = await _create_claim_fixture(fixture_session_factory, created_at=now)
    try:
        async with fixture_session_factory.begin() as worker_a_session:
            locked_tenant_id = await worker_a_session.scalar(
                select(Tenant.id)
                .where(Tenant.id == fixture.tenant_id)
                .with_for_update(key_share=True)
            )
            assert locked_tenant_id == fixture.tenant_id

            claims = await wait_for_lock_sensitive(
                claimer.claim_reserved_for_diagnostic(
                    worker_id="durable-no-key-update-worker",
                    tenant_id=fixture.tenant_id,
                    eligible_at=now,
                ),
                operation="durable claim under Tenant FOR NO KEY UPDATE",
            )
            assert [claim.job_id for claim in claims] == [fixture.job_ids[0]]
    finally:
        await _delete_claim_fixture(fixture_session_factory, fixture)
        await claim_engine.dispose()
        await fixture_engine.dispose()


@pytest.mark.integration
async def test_durable_claim_completes_while_another_worker_holds_short_fair_turn_lock() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 10, 45, tzinfo=UTC)
    claimer = InstrumentedClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    fixture = await _create_claim_fixture(session_factory, created_at=now)
    fair_turn_acquired = asyncio.Event()
    release_fair_turn = asyncio.Event()

    async def hold_one_short_production_fair_turn() -> None:
        async with session_factory.begin() as session:
            row = (
                await session.execute(build_claim_candidates_statement(now=now, limit=1))
            ).first()
            assert row is not None
            tenant: Tenant = row[2]
            assert tenant.id == fixture.tenant_id
            tenant.last_scheduler_turn_at = now + timedelta(microseconds=1)
            await session.flush()
            fair_turn_acquired.set()
            await wait_for_lock_sensitive(
                release_fair_turn.wait(),
                operation="bounded production-shaped fair-turn hold",
            )

    fair_turn_task: asyncio.Task[None] | None = None
    try:
        reserved_tenant = await claimer.reserve_tenant_turn_for_diagnostic(eligible_at=now)
        assert reserved_tenant == fixture.tenant_id

        fair_turn_task = asyncio.create_task(hold_one_short_production_fair_turn())
        await wait_for_lock_sensitive(
            fair_turn_acquired.wait(),
            operation="second worker fair-turn acquisition",
        )
        claims = await wait_for_lock_sensitive(
            claimer.claim_reserved_for_diagnostic(
                worker_id="overlap-durable-worker",
                tenant_id=fixture.tenant_id,
                eligible_at=now,
            ),
            operation="durable claim overlapping a short fair-turn lock",
        )
        assert [claim.job_id for claim in claims] == [fixture.job_ids[0]]
        assert not fair_turn_task.done()
    finally:
        release_fair_turn.set()
        if fair_turn_task is not None:
            await wait_for_lock_sensitive(
                fair_turn_task,
                operation="short fair-turn transaction commit",
            )
        await _delete_claim_fixture(session_factory, fixture)
        await engine.dispose()


@pytest.mark.integration
async def test_fair_turn_reservations_are_mutually_exclusive() -> None:
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
    fixture = await _create_claim_fixture(session_factory, created_at=now)
    try:
        async with session_factory.begin() as worker_a_session:
            worker_a_row = (
                await worker_a_session.execute(build_claim_candidates_statement(now=now, limit=1))
            ).first()
            assert worker_a_row is not None
            assert worker_a_row[2].id == fixture.tenant_id

            async with session_factory.begin() as worker_b_session:
                worker_b_row = (
                    await wait_for_lock_sensitive(
                        worker_b_session.execute(
                            build_claim_candidates_statement(now=now, limit=1)
                        ),
                        operation="competing same-tenant fair-turn reservation",
                    )
                ).first()
                assert worker_b_row is None
    finally:
        await _delete_claim_fixture(session_factory, fixture)
        await engine.dispose()


@pytest.mark.integration
async def test_locked_tenant_fair_turn_does_not_block_another_tenant() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 11, 15, tzinfo=UTC)
    fixture_a = await _create_claim_fixture(session_factory, created_at=now)
    fixture_b = await _create_claim_fixture(
        session_factory,
        created_at=now + timedelta(seconds=1),
    )
    try:
        async with session_factory.begin() as worker_a_session:
            worker_a_row = (
                await worker_a_session.execute(build_claim_candidates_statement(now=now, limit=1))
            ).first()
            assert worker_a_row is not None
            assert worker_a_row[2].id == fixture_a.tenant_id

            async with session_factory.begin() as worker_b_session:
                worker_b_row = (
                    await wait_for_lock_sensitive(
                        worker_b_session.execute(
                            build_claim_candidates_statement(now=now, limit=1)
                        ),
                        operation="other-tenant fair-turn reservation",
                    )
                ).first()
                assert worker_b_row is not None
                assert worker_b_row[2].id == fixture_b.tenant_id
    finally:
        await _delete_claim_fixture(session_factory, fixture_b)
        await _delete_claim_fixture(session_factory, fixture_a)
        await engine.dispose()


@pytest.mark.integration
async def test_phase_a_reservation_crash_leaves_job_claimable_without_a_lease() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 11, 30, tzinfo=UTC)
    crashed_worker = InstrumentedClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    recovery_worker = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    fixture = await _create_claim_fixture(session_factory, created_at=now)
    try:
        reserved_tenant = await crashed_worker.reserve_tenant_turn_for_diagnostic(eligible_at=now)
        assert reserved_tenant == fixture.tenant_id

        async with session_factory() as session:
            job = await session.get(EvaluationJob, fixture.job_ids[0])
            assert job is not None
            assert job.status is JobStatus.QUEUED
            assert job.attempt_count == 0
            assert job.lease_owner is None
            assert job.lease_expires_at is None

        recovered = await wait_for_lock_sensitive(
            recovery_worker.claim(worker_id="reservation-crash-recovery", limit=1),
            operation="claim after committed reservation-only crash",
        )
        assert [claim.job_id for claim in recovered] == [fixture.job_ids[0]]
    finally:
        await _delete_claim_fixture(session_factory, fixture)
        await engine.dispose()


@pytest.mark.integration
async def test_priority_remains_ahead_of_tenant_fairness() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 11, 45, tzinfo=UTC)
    low_priority = await _create_claim_fixture(
        session_factory,
        created_at=now,
        job_count=1,
    )
    high_priority = await _create_claim_fixture(
        session_factory,
        created_at=now + timedelta(seconds=1),
        job_count=1,
    )
    async with session_factory.begin() as session:
        low_job = await session.get(EvaluationJob, low_priority.job_ids[0])
        high_job = await session.get(EvaluationJob, high_priority.job_ids[0])
        assert low_job is not None and high_job is not None
        low_job.priority = 0
        high_job.priority = 10
    claimer = SQLAlchemyJobClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )
    try:
        claims = await wait_for_lock_sensitive(
            claimer.claim(worker_id="priority-worker", limit=2),
            operation="priority-first two-tenant claims",
        )
        assert [claim.job_id for claim in claims] == [
            high_priority.job_ids[0],
            low_priority.job_ids[0],
        ]
    finally:
        await _delete_claim_fixture(session_factory, high_priority)
        await _delete_claim_fixture(session_factory, low_priority)
        await engine.dispose()


@pytest.mark.integration
async def test_ten_workers_drain_one_hundred_same_tenant_jobs_with_limit_one() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    install_postgres_test_timeouts(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    claimer = InstrumentedClaimer(
        session_factory,
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(now),
    )

    async def first_claim(
        worker_number: int,
        *,
        barrier: asyncio.Barrier,
        repetition: int,
    ) -> tuple[ClaimedJob, ...]:
        await barrier.wait()
        return await claimer.claim(
            worker_id=f"limit-one-first-{repetition}-{worker_number}",
            limit=1,
        )

    async def drain(worker_number: int, *, repetition: int) -> tuple[ClaimedJob, ...]:
        drained: list[ClaimedJob] = []
        while True:
            claims = await claimer.claim(
                worker_id=f"limit-one-drain-{repetition}-{worker_number}",
                limit=1,
            )
            if not claims:
                return tuple(drained)
            drained.extend(claims)

    try:
        for repetition in range(20):
            fixture = await _create_claim_fixture(
                session_factory,
                created_at=now,
                job_count=100,
            )
            first_wave_barrier = asyncio.Barrier(11)
            attempts_before = claimer.claim_attempts
            empty_attempts_before = claimer.empty_attempts
            eligible_probes_before = claimer.eligible_probes
            empty_while_eligible_before = claimer.empty_while_eligible
            waiting_fallbacks_before = claimer.waiting_fallbacks

            try:
                first_tasks = [
                    asyncio.create_task(
                        first_claim(
                            index,
                            barrier=first_wave_barrier,
                            repetition=repetition,
                        )
                    )
                    for index in range(10)
                ]
                await first_wave_barrier.wait()
                first_wave = await wait_for_lock_sensitive(
                    asyncio.gather(*first_tasks),
                    operation=f"ten-worker limit-one first wave repetition {repetition + 1}",
                )
                first_claims = tuple(claim for batch in first_wave for claim in batch)
                first_wave_diagnostics = {
                    "repetition": repetition + 1,
                    "claim_requests": len(first_wave),
                    "successful_requests": sum(bool(batch) for batch in first_wave),
                    "claimed_jobs": len(first_claims),
                    "unique_claimed_jobs": len({claim.job_id for claim in first_claims}),
                    "claim_attempts": claimer.claim_attempts - attempts_before,
                    "empty_attempts": claimer.empty_attempts - empty_attempts_before,
                    "eligible_probes": claimer.eligible_probes - eligible_probes_before,
                    "empty_while_eligible": (
                        claimer.empty_while_eligible - empty_while_eligible_before
                    ),
                    "waiting_fallbacks": claimer.waiting_fallbacks - waiting_fallbacks_before,
                }
                write_lock_diagnostic(
                    {
                        "test": "ten_worker_limit_one_repetition",
                        "source": "real_postgresql_ci",
                        "diagnostics": first_wave_diagnostics,
                    }
                )
                assert len(first_claims) == 10, json.dumps(
                    first_wave_diagnostics,
                    sort_keys=True,
                )
                assert len({claim.job_id for claim in first_claims}) == 10, json.dumps(
                    first_wave_diagnostics,
                    sort_keys=True,
                )

                drained_batches = await wait_for_lock_sensitive(
                    asyncio.gather(*(drain(index, repetition=repetition) for index in range(10))),
                    operation=f"ten-worker limit-one queue drain repetition {repetition + 1}",
                )
                claims = first_claims + tuple(claim for batch in drained_batches for claim in batch)
                assert len(claims) == 100
                assert len({claim.job_id for claim in claims}) == 100
                async with session_factory() as session:
                    attempt_count = await session.scalar(
                        select(func.count(JobAttempt.id))
                        .join(EvaluationJob)
                        .where(EvaluationJob.run_id == fixture.run_id)
                    )
                assert attempt_count == 100
            finally:
                await _delete_claim_fixture(session_factory, fixture)
    finally:
        await engine.dispose()


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
        "waiting_fallbacks": claimer.waiting_fallbacks,
        "latency_ms": {
            "points": latencies_ms,
            "p50": median(latencies_ms),
            "p95": quantiles(latencies_ms, n=100, method="inclusive")[94],
            "max": max(latencies_ms),
        },
    }

    write_lock_diagnostic(
        {
            "test": "same_tenant_eight_worker_contention_diagnostics",
            "source": "real_postgresql_ci",
            "diagnostics": diagnostics,
        }
    )

    assert len(claimed_job_ids) == 8, json.dumps(diagnostics, sort_keys=True)
    assert len(set(claimed_job_ids)) == 8, json.dumps(diagnostics, sort_keys=True)
    assert successful_requests == 8, json.dumps(diagnostics, sort_keys=True)
