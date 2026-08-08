import hashlib
import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    Tenant,
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _run(
    *,
    run_id: UUID,
    tenant_id: UUID,
    dataset_version_id: UUID,
    created_by: UUID,
) -> EvaluationRun:
    return EvaluationRun(
        id=run_id,
        tenant_id=tenant_id,
        dataset_version_id=dataset_version_id,
        dataset_hash=_sha256(f"dataset:{dataset_version_id}"),
        idempotency_key=f"rls-{run_id}",
        request_hash=_sha256(f"request:{run_id}"),
        target_type="mock",
        target_config_json={},
        target_config_hash=_sha256(f"target:{run_id}"),
        evaluator_type="execution",
        evaluator_config_json={},
        evaluator_config_hash=_sha256(f"evaluator:{run_id}"),
        target_version="mock-v1",
        evaluator_version="execution-v1",
        total_jobs=1,
        succeeded_jobs=1,
        created_by=created_by,
    )


@pytest.mark.integration
async def test_real_postgresql_rls_is_fail_closed_and_enforces_tenant_writes(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(os.getenv("EVALOPS_REDIS_URL", "redis://localhost:6379/0")),
        artifact_root=tmp_path,
    )
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    role = f"evalops_rls_{uuid4().hex}"
    tenant_ids = (uuid4(), uuid4())
    key_ids = (uuid4(), uuid4())
    dataset_ids = (uuid4(), uuid4())
    reference_ids = (uuid4(), uuid4())
    version_ids = (uuid4(), uuid4())
    run_ids = (uuid4(), uuid4())
    job_ids = (uuid4(), uuid4())
    result_ids = (uuid4(), uuid4())
    blob_hashes = (_sha256(f"rls:{tenant_ids[0]}"), _sha256(f"rls:{tenant_ids[1]}"))
    own_insert_id = uuid4()
    role_created = False

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
            )
            role_created = True
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
                    f"datasets, dataset_versions, evaluation_runs, case_results TO {role}"
                )
            )

        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_id,
                        slug=f"rls-{tenant_id.hex}",
                        name=f"RLS tenant {index}",
                    )
                    for index, tenant_id in enumerate(tenant_ids)
                ]
            )
            await session.flush()
            for index, tenant_id in enumerate(tenant_ids):
                session.add_all(
                    [
                        APIKey(
                            id=key_ids[index],
                            tenant_id=tenant_id,
                            name=f"rls-key-{index}",
                            key_prefix=f"rls_{tenant_id.hex[:12]}",
                            key_hash="not-a-real-key",
                        ),
                        Dataset(
                            id=dataset_ids[index],
                            tenant_id=tenant_id,
                            name=f"rls-dataset-{tenant_id.hex}",
                        ),
                        ArtifactBlob(
                            sha256=blob_hashes[index],
                            byte_size=1,
                            storage_path=f"{blob_hashes[index][:2]}/{blob_hashes[index]}",
                        ),
                    ]
                )
            await session.flush()
            for index, tenant_id in enumerate(tenant_ids):
                session.add(
                    ArtifactReference(
                        id=reference_ids[index],
                        blob_sha256=blob_hashes[index],
                        tenant_id=tenant_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        media_type="application/x-ndjson",
                    )
                )
            await session.flush()
            for index, tenant_id in enumerate(tenant_ids):
                session.add(
                    DatasetVersion(
                        id=version_ids[index],
                        dataset_id=dataset_ids[index],
                        tenant_id=tenant_id,
                        artifact_id=reference_ids[index],
                        version=1,
                        sha256=blob_hashes[index],
                        case_count=1,
                    )
                )
            await session.flush()
            for index, tenant_id in enumerate(tenant_ids):
                session.add(
                    _run(
                        run_id=run_ids[index],
                        tenant_id=tenant_id,
                        dataset_version_id=version_ids[index],
                        created_by=key_ids[index],
                    )
                )
            await session.flush()
            for index, tenant_id in enumerate(tenant_ids):
                session.add(
                    EvaluationJob(
                        id=job_ids[index],
                        run_id=run_ids[index],
                        case_id=f"rls-case-{index}",
                        case_payload_json={},
                        status=JobStatus.SUCCEEDED,
                        attempt_count=1,
                        max_attempts=1,
                    )
                )
                await session.flush()
                session.add(
                    CaseResult(
                        id=result_ids[index],
                        job_id=job_ids[index],
                        run_id=run_ids[index],
                        tenant_id=tenant_id,
                        case_id=f"rls-case-{index}",
                        answer_json={},
                        evidence_json={},
                        metrics_json={},
                        latency_ms=1,
                    )
                )

        async with session_factory.begin() as session:
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            for model in (Dataset, DatasetVersion, EvaluationRun, CaseResult):
                assert (await session.execute(select(model))).scalars().all() == []

        async with session_factory.begin() as session:
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_ids[0])},
            )
            assert {
                row.tenant_id for row in (await session.execute(select(Dataset))).scalars()
            } == {tenant_ids[0]}
            assert {
                row.tenant_id for row in (await session.execute(select(DatasetVersion))).scalars()
            } == {tenant_ids[0]}
            assert {
                row.tenant_id for row in (await session.execute(select(EvaluationRun))).scalars()
            } == {tenant_ids[0]}
            assert {
                row.tenant_id for row in (await session.execute(select(CaseResult))).scalars()
            } == {tenant_ids[0]}

            hidden_update = cast(
                CursorResult[Any],
                await session.execute(
                    update(Dataset)
                    .where(Dataset.id == dataset_ids[1])
                    .values(description="must remain hidden")
                ),
            )
            assert hidden_update.rowcount == 0

        with pytest.raises(DBAPIError, match="row-level security"):
            async with session_factory.begin() as session:
                await session.execute(text(f"SET LOCAL ROLE {role}"))
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_ids[0])},
                )
                await session.execute(
                    insert(Dataset).values(
                        id=uuid4(),
                        tenant_id=tenant_ids[1],
                        name=f"rls-cross-tenant-{uuid4().hex}",
                    )
                )

        with pytest.raises(DBAPIError, match="row-level security"):
            async with session_factory.begin() as session:
                await session.execute(text(f"SET LOCAL ROLE {role}"))
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_ids[0])},
                )
                await session.execute(
                    update(Dataset)
                    .where(Dataset.id == dataset_ids[0])
                    .values(tenant_id=tenant_ids[1])
                )

        async with session_factory.begin() as session:
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_ids[0])},
            )
            await session.execute(
                insert(Dataset).values(
                    id=own_insert_id,
                    tenant_id=tenant_ids[0],
                    name=f"rls-own-tenant-{uuid4().hex}",
                )
            )
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(Dataset).where(Dataset.id == own_insert_id))
            await session.execute(delete(EvaluationJob).where(EvaluationJob.id.in_(job_ids)))
            await session.execute(delete(EvaluationRun).where(EvaluationRun.id.in_(run_ids)))
            await session.execute(delete(DatasetVersion).where(DatasetVersion.id.in_(version_ids)))
            await session.execute(
                delete(ArtifactReference).where(ArtifactReference.id.in_(reference_ids))
            )
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256.in_(blob_hashes)))
            await session.execute(delete(Dataset).where(Dataset.id.in_(dataset_ids)))
            await session.execute(delete(APIKey).where(APIKey.id.in_(key_ids)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        if role_created:
            async with engine.begin() as connection:
                await connection.execute(text(f"DROP OWNED BY {role}"))
                await connection.execute(text(f"DROP ROLE {role}"))
        await engine.dispose()
