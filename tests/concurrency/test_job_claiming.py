import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult, TokenUsage
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.results import SQLAlchemyResultCommitter
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
    job_ids = tuple(uuid4() for _ in range(20))
    try:
        async with session_factory.begin() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=f"claim-{tenant_id.hex}",
                    name="Claim concurrency tenant",
                )
            )
            session.add(
                APIKey(
                    id=api_key_id,
                    tenant_id=tenant_id,
                    name="claim-test",
                    key_prefix=f"ce_{tenant_id.hex[:8]}",
                    key_hash="not-a-real-key",
                )
            )
            session.add(Dataset(id=dataset_id, tenant_id=tenant_id, name="claim-dataset"))
            session.add(
                Artifact(
                    id=artifact_id,
                    tenant_id=tenant_id,
                    artifact_type=ArtifactType.DATASET_SOURCE,
                    sha256="a" * 64,
                    media_type="application/x-ndjson",
                    byte_size=1,
                    storage_path="aa/" + "a" * 64,
                )
            )
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    artifact_id=artifact_id,
                    version=1,
                    schema_version="1",
                    sha256="a" * 64,
                    case_count=20,
                )
            )
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
                    total_jobs=20,
                    created_by=api_key_id,
                )
            )
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
            *(claimer.claim(worker_id=f"worker-{index}", limit=3) for index in range(10))
        )
        claims = tuple(claim for batch in batches for claim in batch)

        assert len(claims) == 20
        assert len({claim.job_id for claim in claims}) == 20
        async with session_factory() as session:
            attempt_count = await session.scalar(
                select(func.count(JobAttempt.id))
                .join(EvaluationJob)
                .where(EvaluationJob.run_id == run_id)
            )
        assert attempt_count == 20

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
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
            await session.execute(delete(CaseResult).where(CaseResult.run_id == run_id))
            await session.execute(delete(JobAttempt).where(JobAttempt.job_id.in_(job_ids)))
            await session.execute(delete(EvaluationJob).where(EvaluationJob.run_id == run_id))
            await session.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
            await session.execute(delete(DatasetVersion).where(DatasetVersion.id == version_id))
            await session.execute(delete(Artifact).where(Artifact.id == artifact_id))
            await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
            await session.execute(delete(APIKey).where(APIKey.id == api_key_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await engine.dispose()
