import asyncio
import os
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, exists, func, select

from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    Tenant,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_real_postgresql_concurrent_run_idempotency_and_tenant_boundary(
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
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
    )
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    generated_a = generate_api_key()
    generated_b = generate_api_key()
    application = create_app(settings=settings)

    async with application.router.lifespan_context(application):
        session_factory = cast(AsyncSessionFactory, application.state.session_factory)
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_a_id,
                        slug=f"run-integration-a-{uuid4().hex}",
                        name="Run integration tenant A",
                    ),
                    Tenant(
                        id=tenant_b_id,
                        slug=f"run-integration-b-{uuid4().hex}",
                        name="Run integration tenant B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        tenant_id=tenant_a_id,
                        name="run-integration-a",
                        key_prefix=generated_a.prefix,
                        key_hash=generated_a.key_hash,
                    ),
                    APIKey(
                        tenant_id=tenant_b_id,
                        name="run-integration-b",
                        key_prefix=generated_b.prefix,
                        key_hash=generated_b.key_hash,
                    ),
                ]
            )

        transport = ASGITransport(app=application)
        headers_a = {
            "Authorization": f"Bearer {generated_a.plaintext.get_secret_value()}",
            "Idempotency-Key": "concurrent-create",
        }
        headers_b = {
            "Authorization": f"Bearer {generated_b.plaintext.get_secret_value()}",
        }
        content = (
            b'{"case_id":"case-1","question":"q1","expected_answer":"a1","metadata":{}}\n'
            b'{"case_id":"case-2","question":"q2","expected_answer":"a2","metadata":{}}\n'
        )
        dataset_id: UUID | None = None
        run_id: UUID | None = None
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                dataset_response = await client.post(
                    "/api/v1/datasets",
                    headers=headers_a,
                    json={"name": f"run-integration-{uuid4().hex}"},
                )
                assert dataset_response.status_code == 201
                dataset_id = UUID(dataset_response.json()["id"])
                version_response = await client.post(
                    f"/api/v1/datasets/{dataset_id}/versions",
                    headers=headers_a,
                    files={"file": ("cases.jsonl", content, "application/x-ndjson")},
                )
                assert version_response.status_code == 201
                version_id = UUID(version_response.json()["id"])
                payload = {
                    "dataset_version_id": str(version_id),
                    "target": {"type": "mock", "version": "target-v1"},
                    "evaluator": {
                        "type": "basic_answer",
                        "version": "eval-v1",
                        "config": {"max_attempts": 3},
                    },
                }

                concurrent_responses = await asyncio.gather(
                    *(
                        client.post("/api/v1/runs", headers=headers_a, json=payload)
                        for _ in range(20)
                    )
                )
                assert {response.status_code for response in concurrent_responses} == {202}
                run_ids = {response.json()["id"] for response in concurrent_responses}
                assert len(run_ids) == 1
                run_id = UUID(run_ids.pop())

                conflict = await client.post(
                    "/api/v1/runs",
                    headers=headers_a,
                    json=payload
                    | {
                        "target": {
                            "type": "mock",
                            "version": "different-target",
                        }
                    },
                )
                assert conflict.status_code == 409
                assert conflict.json()["error"]["code"] == "idempotency_conflict"

                own_get = await client.get(
                    f"/api/v1/runs/{run_id}",
                    headers=headers_a,
                )
                cross_get = await client.get(
                    f"/api/v1/runs/{run_id}",
                    headers=headers_b,
                )
                assert own_get.status_code == 200
                assert cross_get.status_code == 404

                cancelled = await client.post(
                    f"/api/v1/runs/{run_id}/cancel",
                    headers=headers_a,
                )
                replayed_cancel = await client.post(
                    f"/api/v1/runs/{run_id}/cancel",
                    headers=headers_a,
                )
                assert cancelled.status_code == 202
                assert cancelled.json()["status"] == "cancelled"
                assert cancelled.json()["cancelled_jobs"] == 2
                assert replayed_cancel.status_code == 202
                assert replayed_cancel.json()["status"] == "cancelled"

                case_page = await client.get(
                    f"/api/v1/runs/{run_id}/cases",
                    headers=headers_a,
                    params={"limit": 1, "sort": "case_id"},
                )
                cross_case_page = await client.get(
                    f"/api/v1/runs/{run_id}/cases",
                    headers=headers_b,
                )
                assert case_page.status_code == 200
                assert len(case_page.json()["items"]) == 1
                assert case_page.json()["next_cursor"] is not None
                assert cross_case_page.status_code == 404
                second_case_page = await client.get(
                    f"/api/v1/runs/{run_id}/cases",
                    headers=headers_a,
                    params={
                        "limit": 1,
                        "sort": "case_id",
                        "cursor": case_page.json()["next_cursor"],
                    },
                )
                assert second_case_page.status_code == 200
                assert (
                    second_case_page.json()["items"][0]["case_id"]
                    != (case_page.json()["items"][0]["case_id"])
                )

                metrics = await client.get(
                    f"/api/v1/runs/{run_id}/metrics",
                    headers=headers_a,
                )
                assert metrics.status_code == 200
                assert metrics.json()["completion_rate"] == 1.0
                assert metrics.json()["cancellation_rate"] == 1.0

                artifacts = await client.post(
                    f"/api/v1/runs/{run_id}/artifacts",
                    headers=headers_a,
                )
                assert artifacts.status_code == 201
                assert {item["artifact_type"] for item in artifacts.json()} == {
                    "run_metrics",
                    "failure_cases",
                    "summary_report",
                }

                comparison = await client.get(
                    "/api/v1/runs/compare",
                    headers=headers_a,
                    params={
                        "left_run_id": str(run_id),
                        "right_run_id": str(run_id),
                    },
                )
                assert comparison.status_code == 200
                assert comparison.json()["warning"] is None
                assert comparison.json()["intersection_count"] == 2

            async with session_factory() as session:
                run_count = await session.scalar(
                    select(func.count(EvaluationRun.id)).where(
                        EvaluationRun.tenant_id == tenant_a_id,
                        EvaluationRun.idempotency_key == "concurrent-create",
                    )
                )
                job_count = await session.scalar(
                    select(func.count(EvaluationJob.id)).where(EvaluationJob.run_id == run_id)
                )
                case_ids = (
                    (
                        await session.execute(
                            select(EvaluationJob.case_id)
                            .where(EvaluationJob.run_id == run_id)
                            .order_by(EvaluationJob.case_id)
                        )
                    )
                    .scalars()
                    .all()
                )
            assert run_count == 1
            assert job_count == 2
            assert case_ids == ["case-1", "case-2"]
        finally:
            async with session_factory.begin() as session:
                blob_sha256s = list(
                    (
                        await session.execute(
                            select(ArtifactReference.blob_sha256).where(
                                ArtifactReference.tenant_id.in_((tenant_a_id, tenant_b_id))
                            )
                        )
                    ).scalars()
                )
                if run_id is not None:
                    await session.execute(
                        delete(EvaluationJob).where(EvaluationJob.run_id == run_id)
                    )
                    await session.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
                if dataset_id is not None:
                    await session.execute(
                        delete(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
                    )
                    await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
                await session.execute(
                    delete(ArtifactReference).where(
                        ArtifactReference.tenant_id.in_((tenant_a_id, tenant_b_id))
                    )
                )
                await session.flush()
                if blob_sha256s:
                    await session.execute(
                        delete(ArtifactBlob).where(
                            ArtifactBlob.sha256.in_(blob_sha256s),
                            ~exists(
                                select(ArtifactReference.id).where(
                                    ArtifactReference.blob_sha256 == ArtifactBlob.sha256
                                )
                            ),
                        )
                    )
                await session.execute(
                    delete(APIKey).where(APIKey.tenant_id.in_((tenant_a_id, tenant_b_id)))
                )
                await session.execute(
                    delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
                )
