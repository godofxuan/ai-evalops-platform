import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.lease import LeasePolicy
from app.persistence.database import create_database_engine, create_session_factory
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
    Tenant,
)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


@pytest.mark.integration
async def test_tenant_fair_claiming_prevents_older_flood_from_starving_new_tenant() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    tenant_a, tenant_b = uuid4(), uuid4()
    run_a, run_b = uuid4(), uuid4()
    job_ids_a = tuple(uuid4() for _ in range(20))
    job_b = uuid4()
    base_time = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    now = base_time + timedelta(minutes=10)
    resources = {
        tenant_a: _TenantResources.create(tenant_id=tenant_a, run_id=run_a, digest_char="a"),
        tenant_b: _TenantResources.create(tenant_id=tenant_b, run_id=run_b, digest_char="b"),
    }
    try:
        async with session_factory.begin() as session:
            for resource in resources.values():
                session.add(resource.tenant())
            await session.flush()
            for resource in resources.values():
                session.add_all(resource.dependent_records())
            await session.flush()
            for resource in resources.values():
                session.add(resource.dataset_version())
            await session.flush()
            session.add_all(
                [
                    resources[tenant_a].run(total_jobs=len(job_ids_a), created_at=base_time),
                    resources[tenant_b].run(
                        total_jobs=1,
                        created_at=base_time + timedelta(minutes=1),
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EvaluationJob(
                        id=job_id,
                        run_id=run_a,
                        case_id=f"tenant-a-{index:02d}",
                        case_payload_json={"case_id": f"tenant-a-{index:02d}"},
                        status=JobStatus.QUEUED,
                        max_attempts=1,
                        created_at=base_time + timedelta(milliseconds=index),
                    )
                    for index, job_id in enumerate(job_ids_a)
                ]
                + [
                    EvaluationJob(
                        id=job_b,
                        run_id=run_b,
                        case_id="tenant-b-00",
                        case_payload_json={"case_id": "tenant-b-00"},
                        status=JobStatus.QUEUED,
                        max_attempts=1,
                        created_at=base_time + timedelta(minutes=1),
                    )
                ]
            )

        async with session_factory() as session:
            legacy_order = tuple(
                (
                    await session.scalars(
                        select(EvaluationJob.id)
                        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
                        .where(EvaluationRun.tenant_id.in_((tenant_a, tenant_b)))
                        .order_by(
                            EvaluationJob.priority.desc(),
                            EvaluationJob.created_at.asc(),
                            EvaluationJob.id.asc(),
                        )
                    )
                ).all()
            )
        assert legacy_order.index(job_b) + 1 == 21

        claimer = SQLAlchemyJobClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=30)),
            clock=FixedClock(now),
        )
        first_wave = await asyncio.gather(
            claimer.claim(worker_id="fair-worker-1", limit=1),
            claimer.claim(worker_id="fair-worker-2", limit=1),
        )
        claims = tuple(claim for batch in first_wave for claim in batch)

        assert len(claims) == 2
        assert {claim.tenant_id for claim in claims} == {tenant_a, tenant_b}
        assert len({claim.job_id for claim in claims}) == 2
        assert any(claim.job_id == job_b for claim in claims)
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                delete(AuditEvent).where(AuditEvent.tenant_id.in_((tenant_a, tenant_b)))
            )
            await session.execute(
                delete(JobAttempt).where(JobAttempt.job_id.in_((*job_ids_a, job_b)))
            )
            await session.execute(
                delete(EvaluationJob).where(EvaluationJob.run_id.in_((run_a, run_b)))
            )
            await session.execute(delete(EvaluationRun).where(EvaluationRun.id.in_((run_a, run_b))))
            for resource in resources.values():
                await resource.delete(session)
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a, tenant_b))))
        await engine.dispose()


class _TenantResources:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        api_key_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        artifact_id: UUID,
        digest: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.api_key_id = api_key_id
        self.dataset_id = dataset_id
        self.version_id = version_id
        self.artifact_id = artifact_id
        self.digest = digest

    @classmethod
    def create(cls, *, tenant_id: UUID, run_id: UUID, digest_char: str) -> "_TenantResources":
        return cls(
            tenant_id=tenant_id,
            run_id=run_id,
            api_key_id=uuid4(),
            dataset_id=uuid4(),
            version_id=uuid4(),
            artifact_id=uuid4(),
            digest=digest_char * 64,
        )

    def tenant(self) -> Tenant:
        return Tenant(
            id=self.tenant_id,
            slug=f"fair-{self.tenant_id.hex}",
            name="Fairness test tenant",
        )

    def dependent_records(self) -> list[object]:
        return [
            APIKey(
                id=self.api_key_id,
                tenant_id=self.tenant_id,
                name="fairness-test",
                key_prefix=f"cf_{self.tenant_id.hex[:12]}",
                key_hash="not-a-real-key",
            ),
            Dataset(
                id=self.dataset_id,
                tenant_id=self.tenant_id,
                name="fairness-dataset",
            ),
            ArtifactBlob(
                sha256=self.digest,
                byte_size=1,
                storage_path=f"{self.digest[:2]}/{self.digest}",
            ),
            ArtifactReference(
                id=self.artifact_id,
                tenant_id=self.tenant_id,
                artifact_type=ArtifactType.DATASET_SOURCE,
                blob_sha256=self.digest,
                media_type="application/x-ndjson",
            ),
        ]

    def dataset_version(self) -> DatasetVersion:
        return DatasetVersion(
            id=self.version_id,
            dataset_id=self.dataset_id,
            tenant_id=self.tenant_id,
            artifact_id=self.artifact_id,
            version=1,
            schema_version="1",
            sha256=self.digest,
            case_count=1,
        )

    def run(self, *, total_jobs: int, created_at: datetime) -> EvaluationRun:
        return EvaluationRun(
            id=self.run_id,
            tenant_id=self.tenant_id,
            dataset_version_id=self.version_id,
            dataset_hash=self.digest,
            idempotency_key=f"fair-{self.run_id.hex}",
            request_hash=self.digest,
            target_type="mock",
            target_config_json={},
            target_config_hash=self.digest,
            evaluator_type="execution",
            evaluator_config_json={},
            evaluator_config_hash=self.digest,
            target_version="v1",
            evaluator_version="v1",
            status=RunStatus.QUEUED,
            total_jobs=total_jobs,
            created_by=self.api_key_id,
            created_at=created_at,
        )

    async def delete(self, session: AsyncSession) -> None:
        await session.execute(delete(DatasetVersion).where(DatasetVersion.id == self.version_id))
        await session.execute(
            delete(ArtifactReference).where(ArtifactReference.id == self.artifact_id)
        )
        await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == self.digest))
        await session.execute(delete(Dataset).where(Dataset.id == self.dataset_id))
        await session.execute(delete(APIKey).where(APIKey.id == self.api_key_id))
