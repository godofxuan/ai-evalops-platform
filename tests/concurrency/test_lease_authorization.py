"""Real PostgreSQL lock-wait regressions; never substitute SQLite or a fake session."""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.principals import Principal
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory, create_session_factory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProgressEventOutbox,
    Tenant,
)
from app.targets.base import TargetTimeoutError
from tests.postgres_test_support import wait_for_postgres_lock_snapshot, write_lock_diagnostic


@dataclass
class LeaseDatabase:
    factory: AsyncSessionFactory
    blocker_factory: AsyncSessionFactory
    claim: ClaimedJob
    database_url: str
    application_name: str


@pytest.mark.integration
async def test_cancel_refreshes_preflight_state_after_concurrent_completion(
    lease_database: LeaseDatabase,
) -> None:
    db = lease_database
    engine = create_async_engine(
        db.database_url,
        connect_args={
            "application_name": db.application_name + "-stale-cancel",
            "options": "-c lock_timeout=5000 -c statement_timeout=10000",
        },
    )
    gate = int(uuid4().hex[:12], 16)
    paused = False

    def pause_preflight(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal paused
        if (
            not paused
            and statement.startswith("SELECT evaluation_runs.")
            and "FOR UPDATE" not in statement
        ):
            paused = True
            # The real SELECT has already read RUNNING. Hold it before ORM
            # materialization while another transaction commits success.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (gate,))

    event.listen(engine.sync_engine, "after_cursor_execute", pause_preflight)
    task: asyncio.Task[Any] | None = None
    try:
        async with db.factory() as session:
            run = await session.get(EvaluationRun, db.claim.run_id)
            assert run is not None
            principal = Principal(run.tenant_id, run.created_by, "synthetic")
        async with db.blocker_factory.begin() as blocker:
            await blocker.execute(text("SELECT pg_advisory_xact_lock(:gate)"), {"gate": gate})
            task = asyncio.create_task(
                SQLAlchemyCancellationService(create_session_factory(engine)).cancel_run(
                    principal=principal,
                    run_id=db.claim.run_id,
                )
            )
            snapshot = await wait_for_postgres_lock_snapshot(
                db.database_url,
                target_application_name=db.application_name + "-stale-cancel",
                timeout_seconds=2,
            )
            write_lock_diagnostic({"scenario": "cancel_preflight_before_success", **snapshot})
            await SQLAlchemyResultCommitter(db.factory).commit_success(
                claim=db.claim,
                lease_version=db.claim.version,
                target_result=TargetResult(
                    answer="accepted-before-cancel-lock",
                    citations=(),
                    sources=(),
                    trace={},
                    token_usage=None,
                    latency_ms=1,
                ),
                evaluation_result=EvaluationResult(metrics={}),
            )
        response = await asyncio.wait_for(task, 8)
        assert response.status is RunStatus.SUCCEEDED
        async with db.factory() as session:
            run = await session.get(EvaluationRun, db.claim.run_id)
            assert run is not None and run.status is RunStatus.SUCCEEDED
            events = list(
                (
                    await session.scalars(
                        select(ProgressEventOutbox).where(
                            ProgressEventOutbox.run_id == run.id,
                            ProgressEventOutbox.event_type == "run_completed",
                        )
                    )
                ).all()
            )
            assert len(events) == 1, "late cancellation emitted a duplicate terminal event"
            assert run.cancel_requested_at is None
            result = (
                await session.scalars(
                    select(CaseResult).where(CaseResult.job_id == db.claim.job_id)
                )
            ).one()
            assert result.accepted_attempt_id == db.claim.attempt_id
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        event.remove(engine.sync_engine, "after_cursor_execute", pause_preflight)
        await engine.dispose()


@pytest.fixture
async def lease_database() -> AsyncIterator[LeaseDatabase]:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("requires explicit isolated migrated PostgreSQL")
    url = os.environ["EVALOPS_DATABASE_URL"]
    name = "lease-regression-" + uuid4().hex[:12]
    engine = create_async_engine(
        url,
        connect_args={
            "application_name": name,
            "options": "-c lock_timeout=5000 -c statement_timeout=10000",
        },
    )
    blocker_engine = create_async_engine(url, connect_args={"application_name": name + "-blocker"})
    factory = create_session_factory(engine)
    blocker_factory = create_session_factory(blocker_engine)
    tenant, key, dataset, artifact, version, run, job = (uuid4() for _ in range(7))
    digest = uuid4().hex + uuid4().hex
    try:
        async with factory.begin() as session:
            session.add(Tenant(id=tenant, slug=name, name="Isolated lease regression"))
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=key,
                        tenant_id=tenant,
                        name=name,
                        key_prefix=uuid4().hex[:12],
                        key_hash="synthetic-not-a-credential",
                    ),
                    Dataset(id=dataset, tenant_id=tenant, name=name),
                    ArtifactBlob(
                        sha256=digest, byte_size=1, storage_path=digest[:2] + "/" + digest
                    ),
                ]
            )
            await session.flush()
            session.add(
                ArtifactReference(
                    id=artifact,
                    tenant_id=tenant,
                    artifact_type=ArtifactType.DATASET_SOURCE,
                    blob_sha256=digest,
                    media_type="application/x-ndjson",
                )
            )
            await session.flush()
            session.add(
                DatasetVersion(
                    id=version,
                    dataset_id=dataset,
                    tenant_id=tenant,
                    artifact_id=artifact,
                    version=1,
                    schema_version="1",
                    sha256=digest,
                    case_count=1,
                )
            )
            await session.flush()
            session.add(
                EvaluationRun(
                    id=run,
                    tenant_id=tenant,
                    dataset_version_id=version,
                    dataset_hash=digest,
                    idempotency_key=name,
                    request_hash=digest,
                    target_type="mock",
                    target_config_json={},
                    target_config_hash=digest,
                    evaluator_type="execution",
                    evaluator_config_json={},
                    evaluator_config_hash=digest,
                    target_version="v1",
                    evaluator_version="v1",
                    total_jobs=1,
                    created_by=key,
                )
            )
            await session.flush()
            session.add(
                EvaluationJob(
                    id=job,
                    run_id=run,
                    case_id="lock-wait",
                    case_payload_json={"case_id": "lock-wait", "question": "q", "metadata": {}},
                    status=JobStatus.QUEUED,
                    max_attempts=3,
                )
            )
        claims = await SQLAlchemyJobClaimer(
            factory, lease_policy=LeasePolicy(timedelta(seconds=30))
        ).claim(worker_id=name, limit=1)
        assert len(claims) == 1 and claims[0].job_id == job
        yield LeaseDatabase(factory, blocker_factory, claims[0], url, name)
    finally:
        async with factory.begin() as session:
            await session.execute(delete(EvaluationRun).where(EvaluationRun.id == run))
            await session.execute(delete(DatasetVersion).where(DatasetVersion.id == version))
            await session.execute(delete(ArtifactReference).where(ArtifactReference.id == artifact))
            await session.execute(delete(Dataset).where(Dataset.id == dataset))
            await session.execute(delete(APIKey).where(APIKey.id == key))
            await session.execute(delete(Tenant).where(Tenant.id == tenant))
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == digest))
        await engine.dispose()
        await blocker_engine.dispose()


async def _expire_while_blocked(db: LeaseDatabase, operation: Any, *, lock: str) -> Any:
    async with db.factory.begin() as session:
        expiry = await session.scalar(select(func.clock_timestamp() + timedelta(seconds=1)))
        await session.execute(
            update(EvaluationJob)
            .where(EvaluationJob.id == db.claim.job_id)
            .values(lease_expires_at=expiry)
        )
    task = None
    try:
        async with db.blocker_factory.begin() as blocker:
            column, identity = {
                "job": (EvaluationJob.id, db.claim.job_id),
                "run": (EvaluationRun.id, db.claim.run_id),
                "attempt": (JobAttempt.id, db.claim.attempt_id),
            }[lock]
            await blocker.execute(select(column).where(column == identity).with_for_update())
            task = asyncio.create_task(operation())
            snapshot = await wait_for_postgres_lock_snapshot(
                db.database_url,
                target_application_name=db.application_name,
                timeout_seconds=2,
            )
            write_lock_diagnostic({"scenario": "expiry_during_" + lock + "_wait", **snapshot})
            # Lock wait is observed first. Server time, not a random sleep, gates release.
            async with db.blocker_factory() as observer:
                async with asyncio.timeout(3):
                    while True:
                        observed = await observer.scalar(select(func.clock_timestamp()))
                        assert observed is not None and expiry is not None
                        if observed > expiry:
                            break
                        await asyncio.sleep(0.02)
            assert not task.done(), "operation must still be waiting on the held row lock"
        return await asyncio.wait_for(task, timeout=5)
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["result", "failure"])
async def test_commit_metrics_retain_expiry_rejection_after_real_lock_wait(
    lease_database: LeaseDatabase, operation: str
) -> None:
    db = lease_database
    metrics = PlatformMetrics()

    async def commit() -> None:
        if operation == "result":
            await SQLAlchemyResultCommitter(db.factory, metrics=metrics).commit_success(
                claim=db.claim,
                lease_version=db.claim.version,
                target_result=TargetResult(
                    answer="a", citations=(), sources=(), trace={}, token_usage=None, latency_ms=1
                ),
                evaluation_result=EvaluationResult(metrics={}),
            )
        else:
            await SQLAlchemyFailureCommitter(
                db.factory, retry_policy=RetryPolicy(), metrics=metrics
            ).commit_failure(
                claim=db.claim,
                lease_version=db.claim.version,
                error=TargetTimeoutError(),
            )

    with pytest.raises(LeaseLostError):
        await _expire_while_blocked(db, commit, lock="run")
    assert (
        metrics.registry.get_sample_value(
            "job_lease_authorization_total", {"operation": operation, "outcome": "expired"}
        )
        == 1
    )
    seconds = metrics.registry.get_sample_value(
        "job_lease_lock_query_seconds_sum", {"operation": operation}
    )
    assert seconds is not None and seconds >= 0.5


@pytest.mark.integration
async def test_reaper_metrics_count_only_committed_expiry_lag(
    lease_database: LeaseDatabase,
) -> None:
    db = lease_database
    metrics = PlatformMetrics()
    async with db.factory.begin() as session:
        await session.execute(
            update(EvaluationJob)
            .where(EvaluationJob.id == db.claim.job_id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=5))
        )
    recovered = await SQLAlchemyJobReaper(
        db.factory, retry_policy=RetryPolicy(), metrics=metrics
    ).reap()
    assert len(recovered) == 1
    assert metrics.registry.get_sample_value("job_reaper_expiry_lag_seconds_count") == 1
    lag = metrics.registry.get_sample_value("job_reaper_expiry_lag_seconds_sum")
    assert lag is not None and lag >= 5
    await SQLAlchemyJobReaper(db.factory, retry_policy=RetryPolicy(), metrics=metrics).reap()
    assert metrics.registry.get_sample_value("job_reaper_expiry_lag_seconds_count") == 1


@pytest.mark.integration
async def test_rolled_back_recovery_does_not_publish_reaper_lag(
    lease_database: LeaseDatabase,
) -> None:
    from sqlalchemy.orm import Session

    db = lease_database
    metrics = PlatformMetrics()
    async with db.factory.begin() as session:
        await session.execute(
            update(EvaluationJob)
            .where(EvaluationJob.id == db.claim.job_id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=5))
        )

    def reject_commit(session: Session) -> None:
        raise RuntimeError("injected transaction commit failure")

    event.listen(Session, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError, match="injected transaction"):
            await SQLAlchemyJobReaper(
                db.factory, retry_policy=RetryPolicy(), metrics=metrics
            ).reap()
    finally:
        event.remove(Session, "before_commit", reject_commit)
    assert metrics.registry.get_sample_value("job_reaper_expiry_lag_seconds_count") == 0
    async with db.factory() as session:
        job = await session.get(EvaluationJob, db.claim.job_id)
        assert job is not None and job.status is JobStatus.RUNNING


@pytest.mark.integration
async def test_heartbeat_metrics_report_real_lock_wait_and_expiry_rejection(
    lease_database: LeaseDatabase,
) -> None:
    db = lease_database
    metrics = PlatformMetrics()
    service = SQLAlchemyHeartbeatService(
        db.factory, lease_duration=timedelta(seconds=30), metrics=metrics
    )
    with pytest.raises(LeaseLostError):
        await _expire_while_blocked(
            db,
            lambda: service.heartbeat(
                job_id=db.claim.job_id,
                worker_id=db.claim.worker_id,
                expected_version=db.claim.version,
            ),
            lock="job",
        )
    assert (
        metrics.registry.get_sample_value(
            "job_lease_authorization_total", {"operation": "heartbeat", "outcome": "expired"}
        )
        == 1
    )
    seconds = metrics.registry.get_sample_value(
        "job_lease_lock_query_seconds_sum", {"operation": "heartbeat"}
    )
    assert seconds is not None and seconds >= 0.5
    exposed = metrics.render().decode()
    assert str(db.claim.job_id) not in exposed
    assert db.claim.worker_id not in exposed


@pytest.mark.integration
async def test_heartbeat_rejects_lease_expired_during_real_job_lock_wait(
    lease_database: LeaseDatabase,
) -> None:
    db = lease_database
    heartbeat = SQLAlchemyHeartbeatService(db.factory, lease_duration=timedelta(seconds=30))
    with pytest.raises(LeaseLostError):
        await _expire_while_blocked(
            db,
            lambda: heartbeat.heartbeat(
                job_id=db.claim.job_id,
                worker_id=db.claim.worker_id,
                expected_version=db.claim.version,
            ),
            lock="job",
        )
    async with db.factory() as session:
        job = await session.get(EvaluationJob, db.claim.job_id)
        assert job is not None and job.version == db.claim.version
        assert job.status == JobStatus.RUNNING


@pytest.mark.integration
async def test_renewal_starts_after_wait_longer_than_renewal_duration(
    lease_database: LeaseDatabase,
) -> None:
    db = lease_database
    duration = timedelta(milliseconds=100)
    task = None
    try:
        async with db.blocker_factory.begin() as blocker:
            await blocker.execute(
                select(EvaluationJob.id)
                .where(EvaluationJob.id == db.claim.job_id)
                .with_for_update()
            )
            started = await blocker.scalar(select(func.clock_timestamp()))
            assert isinstance(started, datetime)
            task = asyncio.create_task(
                SQLAlchemyHeartbeatService(db.factory, lease_duration=duration).heartbeat(
                    job_id=db.claim.job_id,
                    worker_id=db.claim.worker_id,
                    expected_version=db.claim.version,
                )
            )
            await wait_for_postgres_lock_snapshot(
                db.database_url, target_application_name=db.application_name, timeout_seconds=2
            )
            async with asyncio.timeout(3):
                while True:
                    released_after = await blocker.scalar(select(func.clock_timestamp()))
                    assert isinstance(released_after, datetime)
                    if released_after > started + 2 * duration:
                        break
                    await asyncio.sleep(0.01)
            assert not task.done()
        receipt = await asyncio.wait_for(task, 5)
        assert receipt.version == db.claim.version + 1
        assert receipt.lease_expires_at >= released_after + duration
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.integration
@pytest.mark.parametrize("condition", ["owner", "version", "equal_expiry"])
async def test_real_database_lease_identity_and_equality_controls(
    lease_database: LeaseDatabase, condition: str
) -> None:
    db = lease_database
    async with db.factory.begin() as session:
        boundary = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(boundary, datetime)
        if condition == "equal_expiry":
            await session.execute(
                update(EvaluationJob)
                .where(EvaluationJob.id == db.claim.job_id)
                .values(lease_expires_at=boundary)
            )

    class BoundaryClock:
        def now(self) -> datetime:
            assert isinstance(boundary, datetime)
            return boundary

    # Only the exact-equality control injects time; other cases use real DB time.
    metrics = PlatformMetrics()
    service = SQLAlchemyHeartbeatService(
        db.factory,
        lease_duration=timedelta(seconds=30),
        clock=BoundaryClock() if condition == "equal_expiry" else None,
        metrics=metrics,
    )
    with pytest.raises(LeaseLostError):
        await service.heartbeat(
            job_id=db.claim.job_id,
            worker_id="wrong-owner" if condition == "owner" else db.claim.worker_id,
            expected_version=db.claim.version + (1 if condition == "version" else 0),
        )
    assert (
        metrics.registry.get_sample_value(
            "job_lease_authorization_total",
            {
                "operation": "heartbeat",
                "outcome": "expired" if condition == "equal_expiry" else condition,
            },
        )
        == 1
    )
    async with db.factory() as session:
        job = await session.get(EvaluationJob, db.claim.job_id)
        assert job is not None and job.version == db.claim.version
        assert job.status == JobStatus.RUNNING


@pytest.mark.integration
@pytest.mark.parametrize("lock", ["run", "job", "attempt"])
async def test_success_rejects_lease_expired_during_final_lock_wait(
    lease_database: LeaseDatabase,
    lock: str,
) -> None:
    db = lease_database
    committer = SQLAlchemyResultCommitter(db.factory)
    with pytest.raises(LeaseLostError):
        await _expire_while_blocked(
            db,
            lambda: committer.commit_success(
                claim=db.claim,
                lease_version=db.claim.version,
                target_result=TargetResult(
                    answer="a",
                    citations=(),
                    sources=(),
                    trace={},
                    token_usage=None,
                    latency_ms=1,
                ),
                evaluation_result=EvaluationResult(metrics={"score": 1.0}),
            ),
            lock=lock,
        )
    async with db.factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CaseResult)
                .where(CaseResult.job_id == db.claim.job_id)
            )
            == 0
        )
        attempt = await session.get(JobAttempt, db.claim.attempt_id)
        assert attempt is not None and attempt.finished_at is None


@pytest.mark.integration
@pytest.mark.parametrize("_schedule", range(20))
async def test_reaper_and_result_do_not_form_run_job_wait_cycle(
    lease_database: LeaseDatabase,
    _schedule: int,
) -> None:
    db = lease_database
    gate = int(uuid4().hex[:7], 16)
    result_name = db.application_name + "-commit"
    result_engine = create_async_engine(
        db.database_url,
        connect_args={
            "application_name": result_name,
            "options": "-c lock_timeout=5000 -c statement_timeout=10000",
        },
    )
    result_factory = create_session_factory(result_engine)
    gate_seen = False

    def after_run_lock(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal gate_seen
        del cursor, parameters, context, executemany
        if (
            not gate_seen
            and statement.startswith("SELECT evaluation_runs.id")
            and "FOR" in statement
        ):
            gate_seen = True
            # Instrument the real DB boundary, without replacing either service.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (gate,))

    event.listen(result_engine.sync_engine, "after_cursor_execute", after_run_lock)
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with db.factory.begin() as session:
            await session.execute(
                update(EvaluationJob)
                .where(EvaluationJob.id == db.claim.job_id)
                .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        async with db.blocker_factory.begin() as blocker:
            await blocker.execute(text("SELECT pg_advisory_xact_lock(:gate)"), {"gate": gate})
            result_task = asyncio.create_task(
                SQLAlchemyResultCommitter(result_factory).commit_success(
                    claim=db.claim,
                    lease_version=db.claim.version,
                    target_result=TargetResult(
                        answer="a",
                        citations=(),
                        sources=(),
                        trace={},
                        token_usage=None,
                        latency_ms=1,
                    ),
                    evaluation_result=EvaluationResult(metrics={"score": 1.0}),
                )
            )
            tasks.append(result_task)
            try:
                snapshot = await wait_for_postgres_lock_snapshot(
                    db.database_url,
                    target_application_name=result_name,
                    timeout_seconds=2,
                )
            except AssertionError:
                if result_task.done():
                    result_task.result()
                raise
            write_lock_diagnostic({"scenario": "committer_holds_run_at_test_gate", **snapshot})
            reaper_task = asyncio.create_task(
                SQLAlchemyJobReaper(
                    db.factory,
                    retry_policy=RetryPolicy(),
                ).reap(limit=1)
            )
            tasks.append(reaper_task)
            try:
                snapshot = await wait_for_postgres_lock_snapshot(
                    db.database_url,
                    target_application_name=db.application_name,
                    timeout_seconds=0.5,
                )
            except AssertionError:
                assert reaper_task.done(), "reaper must yield a busy Run instead of holding Job"
            else:
                write_lock_diagnostic(
                    {"scenario": "reaper_waiting_run_before_gate_release", **snapshot}
                )
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=8)
        database_errors = [outcome for outcome in outcomes if isinstance(outcome, DBAPIError)]
        print("REAPER_RESULT_OUTCOMES", [type(outcome).__name__ for outcome in outcomes])
        assert not database_errors, repr(database_errors)
        assert isinstance(outcomes[0], LeaseLostError), outcomes
        # A skip is permitted, but the same expired Job must be recoverable next pass.
        await SQLAlchemyJobReaper(db.factory, retry_policy=RetryPolicy()).reap(limit=1)
        async with db.factory() as session:
            job = await session.get(EvaluationJob, db.claim.job_id)
            assert job is not None and job.status == JobStatus.RETRY_WAIT
            assert (
                await session.scalar(
                    select(func.count()).select_from(CaseResult).where(CaseResult.job_id == job.id)
                )
                == 0
            )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event.remove(result_engine.sync_engine, "after_cursor_execute", after_run_lock)
        await result_engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("lock", ["run", "job", "attempt"])
async def test_failure_rejects_lease_expired_during_final_lock_wait(
    lease_database: LeaseDatabase,
    lock: str,
) -> None:
    db = lease_database
    committer = SQLAlchemyFailureCommitter(db.factory, retry_policy=RetryPolicy())
    with pytest.raises(LeaseLostError):
        await _expire_while_blocked(
            db,
            lambda: committer.commit_failure(
                claim=db.claim,
                lease_version=db.claim.version,
                error=TargetTimeoutError(),
            ),
            lock=lock,
        )
    async with db.factory() as session:
        job = await session.get(EvaluationJob, db.claim.job_id)
        attempt = await session.get(JobAttempt, db.claim.attempt_id)
        assert job is not None and job.status == JobStatus.RUNNING
        assert job.version == db.claim.version
        assert attempt is not None and attempt.finished_at is None


@pytest.mark.integration
@pytest.mark.parametrize("initial_status", [RunStatus.QUEUED, RunStatus.RUNNING])
async def test_claim_does_not_wait_for_parent_while_cancellation_holds_run(
    lease_database: LeaseDatabase,
    initial_status: RunStatus,
) -> None:
    from app.auth.principals import Principal
    from app.jobs.cancellation import SQLAlchemyCancellationService

    db = lease_database
    gate = int(uuid4().hex[:7], 16)
    engine = create_async_engine(
        db.database_url,
        connect_args={
            "application_name": db.application_name + "-cancel",
            "options": "-c lock_timeout=5000 -c statement_timeout=10000",
        },
    )
    seen = False

    def pause_cancel(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal seen
        if (
            not seen
            and statement.startswith("SELECT evaluation_runs.")
            and "FOR UPDATE" in statement
        ):
            seen = True
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (gate,))

    event.listen(engine.sync_engine, "after_cursor_execute", pause_cancel)
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with db.factory.begin() as session:
            await session.execute(delete(JobAttempt).where(JobAttempt.job_id == db.claim.job_id))
            await session.execute(
                update(EvaluationJob)
                .where(EvaluationJob.id == db.claim.job_id)
                .values(
                    status=JobStatus.QUEUED,
                    attempt_count=0,
                    lease_owner=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
            )
            run = await session.get(EvaluationRun, db.claim.run_id)
            assert run is not None
            run.status = initial_status
            principal = Principal(
                tenant_id=run.tenant_id, api_key_id=run.created_by, key_prefix="synthetic"
            )
        async with db.blocker_factory.begin() as blocker:
            await blocker.execute(text("SELECT pg_advisory_xact_lock(:gate)"), {"gate": gate})
            tasks.append(
                asyncio.create_task(
                    SQLAlchemyCancellationService(create_session_factory(engine)).cancel_run(
                        principal=principal, run_id=db.claim.run_id
                    )
                )
            )
            snapshot = await wait_for_postgres_lock_snapshot(
                db.database_url,
                target_application_name=db.application_name + "-cancel",
                timeout_seconds=2,
            )
            write_lock_diagnostic({"scenario": "cancel_holds_parent", **snapshot})
            tasks.append(
                asyncio.create_task(
                    SQLAlchemyJobClaimer(
                        db.factory, lease_policy=LeasePolicy(timedelta(seconds=30))
                    ).claim(worker_id="claim-cancel-control")
                )
            )
            try:
                snapshot = await wait_for_postgres_lock_snapshot(
                    db.database_url,
                    target_application_name=db.application_name,
                    timeout_seconds=0.3,
                )
                write_lock_diagnostic({"scenario": "claim_waits_parent", **snapshot})
            except AssertionError:
                pass  # Nonblocking admission is allowed to retry until cancel commits.
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 8)
        assert not [value for value in outcomes if isinstance(value, BaseException)], repr(outcomes)
        assert outcomes[1] == ()
        async with db.factory() as session:
            job = await session.get(EvaluationJob, db.claim.job_id)
            assert job is not None and job.status == JobStatus.CANCELLED
            assert job.attempt_count == 0
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event.remove(engine.sync_engine, "after_cursor_execute", pause_cancel)
        await engine.dispose()
