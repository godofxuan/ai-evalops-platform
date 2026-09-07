import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from app.auth.api_keys import generate_api_key
from app.auth.principals import Principal
from app.core.config import Settings
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    ArtifactReference,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    ProductExperiment,
    Tenant,
)
from app.product_experiments.persistence import (
    NewProductExperiment,
    SQLAlchemyProductExperimentRepository,
)
from app.runs.schemas import RunCreate
from app.runs.service import IdempotencyConflictError, SQLAlchemyRunService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_real_postgres_pair_idempotency_and_hidden_tenant_boundary(tmp_path: Path) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("requires isolated migrated PostgreSQL")
    database_url = os.environ["EVALOPS_DATABASE_URL"]
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(os.environ["EVALOPS_REDIS_URL"]),
        artifact_root=tmp_path,
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
    )
    application = create_app(settings=settings)
    tenant_id, key_id = uuid4(), uuid4()
    credential = generate_api_key()
    async with application.router.lifespan_context(application):
        factory = cast(AsyncSessionFactory, application.state.session_factory)
        async with factory.begin() as session:
            session.add(Tenant(id=tenant_id, slug=f"pair-{tenant_id.hex}", name="Pair test"))
            await session.flush()
            session.add(
                APIKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    name="pair-test",
                    key_prefix=credential.prefix,
                    key_hash=credential.key_hash,
                )
            )
        headers = {"Authorization": f"Bearer {credential.plaintext.get_secret_value()}"}
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/datasets", headers=headers, json={"name": "pair"})
            assert response.status_code == 201
            dataset_id = response.json()["id"]
            content = (
                b'{"case_id":"q1","question":"q","expected_answer":"a","metadata":{}}\n'
                b'{"case_id":"q2","question":"q","expected_answer":"a","metadata":{}}\n'
            )
            response = await client.post(
                f"/api/v1/datasets/{dataset_id}/versions",
                headers=headers,
                files={"file": ("cases.jsonl", content, "application/x-ndjson")},
            )
            assert response.status_code == 201
            dataset_version = UUID(response.json()["id"])
        service = cast(SQLAlchemyRunService, application.state.run_service)
        principal = Principal(tenant_id=tenant_id, api_key_id=key_id, key_prefix=credential.prefix)
        request = RunCreate.model_validate(
            {
                "dataset_version_id": str(dataset_version),
                "target": {"type": "mock", "version": "v1"},
                "evaluator": {"type": "basic_answer", "version": "builtin-v1"},
            }
        )
        baseline = await service.prepare_run(
            principal=principal, idempotency_key="b", request=request
        )
        candidate = replace(baseline, idempotency_key="c", target_version="v2")
        pending = NewProductExperiment(
            tenant_id=tenant_id,
            created_by=key_id,
            idempotency_key="same-pair",
            request_hash="a" * 64,
            snapshot={"schema_version": "integration-only"},
            baseline=baseline,
            candidate=candidate,
        )
        repository = SQLAlchemyProductExperimentRepository(factory)
        results = await asyncio.gather(*(repository.create_or_replay(pending) for _ in range(8)))
        assert len({result.id for result in results}) == 1
        pair = results[0]
        assert pair.baseline_run_id != pair.candidate_run_id
        assert await repository.get(tenant_id=uuid4(), experiment_id=pair.id) is None
        assert (await repository.get(tenant_id=tenant_id, experiment_id=pair.id)) == pair
        with pytest.raises(IdempotencyConflictError):
            await repository.create_or_replay(replace(pending, request_hash="b" * 64))
        inserted_versions: list[str] = []

        def fail_second_arm(
            _mapper: Mapper[EvaluationRun], _connection: Connection, target: EvaluationRun
        ) -> None:
            inserted_versions.append(target.target_version)
            if target.target_version == "v2":
                raise RuntimeError("injected second-arm insert failure")

        event.listen(EvaluationRun, "before_insert", fail_second_arm)
        try:
            with pytest.raises(RuntimeError, match="second-arm"):
                await repository.create_or_replay(replace(pending, idempotency_key="rollback-pair"))
        finally:
            event.remove(EvaluationRun, "before_insert", fail_second_arm)
        assert inserted_versions == ["v1", "v2"]
        assert (
            await repository.find_by_key(tenant_id=tenant_id, idempotency_key="rollback-pair")
            is None
        )
        async with factory() as session:
            runs = (
                (
                    await session.execute(
                        select(EvaluationRun.id).where(EvaluationRun.tenant_id == tenant_id)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                (
                    await session.execute(
                        select(EvaluationJob.id).where(EvaluationJob.run_id.in_(runs))
                    )
                )
                .scalars()
                .all()
            )
        assert len(runs) == 2 and len(jobs) == 4
        async with factory.begin() as session:
            await session.execute(
                delete(ProductExperiment).where(ProductExperiment.tenant_id == tenant_id)
            )
            await session.execute(delete(EvaluationJob).where(EvaluationJob.run_id.in_(runs)))
            await session.execute(delete(EvaluationRun).where(EvaluationRun.tenant_id == tenant_id))
            await session.execute(
                delete(DatasetVersion).where(DatasetVersion.id == dataset_version)
            )
            await session.execute(delete(Dataset).where(Dataset.id == UUID(dataset_id)))
            await session.execute(
                delete(ArtifactReference).where(ArtifactReference.tenant_id == tenant_id)
            )
            await session.execute(delete(APIKey).where(APIKey.id == key_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
