import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.auth.principals import Principal
from app.core.config import Settings
from app.domain.enums import ArtifactType, AttemptOutcome, JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult, TokenUsage
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import (
    APIKey,
    Artifact,
    AuditEvent,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    Tenant,
)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class FixedRandom:
    def random(self) -> float:
        return 0.5


@pytest.mark.integration
async def test_ten_workers_claim_each_job_once_and_stale_heartbeats_are_rejected(
    tmp_path: object,
) -> None:
    del tmp_path
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    clock = FixedClock(now)
    tenant_id = uuid4()
    run_id = uuid4()
    dataset_id = uuid4()
    version_id = uuid4()
    api_key_id = uuid4()
    artifact_id = uuid4()
    job_ids = tuple(uuid4() for _ in range(100))
    race_run_id = uuid4()
    race_job_id = uuid4()
    try:
        async with session_factory.begin() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=f"claim-{tenant_id.hex}",
                    name="Claim concurrency tenant",
                )
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=api_key_id,
                        tenant_id=tenant_id,
                        name="claim-test",
                        key_prefix=f"ce_{tenant_id.hex[:8]}",
                        key_hash="not-a-real-key",
                    ),
                    Dataset(id=dataset_id, tenant_id=tenant_id, name="claim-dataset"),
                    Artifact(
                        id=artifact_id,
                        tenant_id=tenant_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        sha256="a" * 64,
                        media_type="application/x-ndjson",
                        byte_size=1,
                        storage_path="aa/" + "a" * 64,
                    ),
                ]
            )
            await session.flush()
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    artifact_id=artifact_id,
                    version=1,
                    schema_version="1",
                    sha256="a" * 64,
                    case_count=100,
                )
            )
            await session.flush()
            session.add(
                EvaluationRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    dataset_version_id=version_id,
                    dataset_hash="a" * 64,
                    idempotency_key=f"claim-{run_id.hex}",
                    request_hash="b" * 64,
                    target_type="mock",
                    target_config_json={"type": "mock"},
                    target_config_hash="c" * 64,
                    evaluator_type="execution",
                    evaluator_config_json={"type": "execution"},
                    evaluator_config_hash="d" * 64,
                    target_version="v1",
                    evaluator_version="v1",
                    status=RunStatus.QUEUED,
                    total_jobs=100,
                    created_by=api_key_id,
                )
            )
            await session.flush()
            session.add_all(
                [
                    EvaluationJob(
                        id=job_id,
                        run_id=run_id,
                        case_id=f"case-{index:02d}",
                        case_payload_json={"case_id": f"case-{index:02d}", "question": "q"},
                        status=JobStatus.QUEUED,
                        max_attempts=3,
                    )
                    for index, job_id in enumerate(job_ids)
                ]
            )

        claimer = SQLAlchemyJobClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=30)),
            clock=clock,
        )
        batches = await asyncio.gather(
            *(claimer.claim(worker_id=f"worker-{index}", limit=20) for index in range(10))
        )
        claims = tuple(claim for batch in batches for claim in batch)

        assert len(claims) == 100
        assert len({claim.job_id for claim in claims}) == 100
        async with session_factory() as session:
            attempt_count = await session.scalar(
                select(func.count(JobAttempt.id))
                .join(EvaluationJob)
                .where(EvaluationJob.run_id == run_id)
            )
        assert attempt_count == 100

        first = claims[0]
        heartbeat = SQLAlchemyHeartbeatService(
            session_factory,
            lease_duration=timedelta(seconds=30),
            clock=clock,
        )
        receipt = await heartbeat.heartbeat(
            job_id=first.job_id,
            worker_id=first.worker_id,
            expected_version=first.version,
        )
        assert receipt.version == first.version + 1

        with pytest.raises(LeaseLostError):
            await heartbeat.heartbeat(
                job_id=first.job_id,
                worker_id=first.worker_id,
                expected_version=first.version,
            )
        with pytest.raises(LeaseLostError):
            await heartbeat.heartbeat(
                job_id=first.job_id,
                worker_id="stale-worker",
                expected_version=receipt.version,
            )

        committer = SQLAlchemyResultCommitter(session_factory, clock=clock)
        target_result = TargetResult(
            answer="answer",
            citations=(),
            sources=(),
            trace={},
            token_usage=TokenUsage(input_tokens=3, output_tokens=1),
            latency_ms=10,
        )
        evaluation_result = EvaluationResult(metrics={"execution_success": True})
        await committer.commit_success(
            claim=first,
            lease_version=receipt.version,
            target_result=target_result,
            evaluation_result=evaluation_result,
        )
        with pytest.raises(LeaseLostError):
            await committer.commit_success(
                claim=first,
                lease_version=receipt.version,
                target_result=target_result,
                evaluation_result=evaluation_result,
            )
        async with session_factory() as session:
            result_count = await session.scalar(
                select(func.count(CaseResult.id)).where(CaseResult.job_id == first.job_id)
            )
        assert result_count == 1

        expired_at = now + timedelta(seconds=31)
        retry_policy = RetryPolicy(
            base_delay_seconds=1,
            max_delay_seconds=60,
            jitter_ratio=0,
            random_source=FixedRandom(),
        )
        reaper_a = SQLAlchemyJobReaper(
            session_factory,
            retry_policy=retry_policy,
            clock=FixedClock(expired_at),
            reaper_id="reaper-a",
        )
        reaper_b = SQLAlchemyJobReaper(
            session_factory,
            retry_policy=retry_policy,
            clock=FixedClock(expired_at),
            reaper_id="reaper-b",
        )
        reaped_batches = await asyncio.gather(
            reaper_a.reap(limit=100),
            reaper_b.reap(limit=100),
        )
        reaped = tuple(item for batch in reaped_batches for item in batch)
        assert len(reaped) == 99
        assert len({item.job_id for item in reaped}) == 99
        assert all(item.status is JobStatus.RETRY_WAIT for item in reaped)
        async with session_factory() as session:
            retry_wait_count = await session.scalar(
                select(func.count(EvaluationJob.id)).where(
                    EvaluationJob.run_id == run_id,
                    EvaluationJob.status == JobStatus.RETRY_WAIT,
                )
            )
            expired_attempt_count = await session.scalar(
                select(func.count(JobAttempt.id))
                .join(EvaluationJob)
                .where(
                    EvaluationJob.run_id == run_id,
                    JobAttempt.outcome == AttemptOutcome.LEASE_EXPIRED,
                )
            )
        assert retry_wait_count == 99
        assert expired_attempt_count == 99

        async with session_factory.begin() as session:
            session.add(
                EvaluationRun(
                    id=race_run_id,
                    tenant_id=tenant_id,
                    dataset_version_id=version_id,
                    dataset_hash="a" * 64,
                    idempotency_key=f"race-{race_run_id.hex}",
                    request_hash="e" * 64,
                    target_type="mock",
                    target_config_json={"type": "mock"},
                    target_config_hash="f" * 64,
                    evaluator_type="execution",
                    evaluator_config_json={"type": "execution"},
                    evaluator_config_hash="1" * 64,
                    target_version="v1",
                    evaluator_version="v1",
                    status=RunStatus.QUEUED,
                    total_jobs=1,
                    created_by=api_key_id,
                )
            )
            session.add(
                EvaluationJob(
                    id=race_job_id,
                    run_id=race_run_id,
                    case_id="cancel-result-race",
                    case_payload_json={
                        "case_id": "cancel-result-race",
                        "question": "q",
                    },
                    status=JobStatus.QUEUED,
                    max_attempts=1,
                )
            )
        race_claim = (await claimer.claim(worker_id="race-worker", limit=1))[0]
        cancellation = SQLAlchemyCancellationService(
            session_factory,
            clock=clock,
        )
        principal = Principal(
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            key_prefix="race_key",
        )
        race_outcomes = await asyncio.gather(
            cancellation.cancel_run(
                principal=principal,
                run_id=race_run_id,
            ),
            committer.commit_success(
                claim=race_claim,
                lease_version=race_claim.version,
                target_result=target_result,
                evaluation_result=evaluation_result,
            ),
            return_exceptions=True,
        )
        assert not any(isinstance(outcome, BaseException) for outcome in race_outcomes)
        async with session_factory() as session:
            race_result_count = await session.scalar(
                select(func.count(CaseResult.id)).where(CaseResult.job_id == race_job_id)
            )
            race_job_status = await session.scalar(
                select(EvaluationJob.status).where(EvaluationJob.id == race_job_id)
            )
            race_run_status = await session.scalar(
                select(EvaluationRun.status).where(EvaluationRun.id == race_run_id)
            )
        assert race_result_count == 1
        assert race_job_status is JobStatus.SUCCEEDED
        assert race_run_status is RunStatus.SUCCEEDED
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
            await session.execute(
                delete(CaseResult).where(CaseResult.run_id.in_((run_id, race_run_id)))
            )
            await session.execute(
                delete(JobAttempt).where(JobAttempt.job_id.in_((*job_ids, race_job_id)))
            )
            await session.execute(
                delete(EvaluationJob).where(EvaluationJob.run_id.in_((run_id, race_run_id)))
            )
            await session.execute(
                delete(EvaluationRun).where(EvaluationRun.id.in_((run_id, race_run_id)))
            )
            await session.execute(delete(DatasetVersion).where(DatasetVersion.id == version_id))
            await session.execute(delete(Artifact).where(Artifact.id == artifact_id))
            await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
            await session.execute(delete(APIKey).where(APIKey.id == api_key_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await engine.dispose()
