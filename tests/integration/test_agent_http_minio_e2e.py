import asyncio
import hashlib
import os
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, exists, select

from app.agent_eval.service import SQLAlchemyAgentArtifactService
from app.artifacts.storage import DeletableArtifactStore, StoredArtifact
from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AgentRegressionComparison,
    AgentRegressionEvidence,
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    HumanReviewTask,
    Tenant,
)
from app.reviews.service import SQLAlchemyReviewService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class InstrumentedArtifactStore:
    def __init__(self, inner: DeletableArtifactStore) -> None:
        self.inner = inner
        self.get_count = 0

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        return await self.inner.put_bytes(content)

    async def get_bytes(self, sha256: str) -> bytes:
        self.get_count += 1
        return await self.inner.get_bytes(sha256)

    async def check_ready(self) -> None:
        await self.inner.check_ready()

    async def delete_bytes(self, sha256: str) -> bool:
        return await self.inner.delete_bytes(sha256)


def _minio_settings(database_url: str) -> Settings:
    if os.getenv("EVALOPS_RUN_MINIO_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_MINIO_INTEGRATION=1 for real MinIO integration")
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(os.getenv("EVALOPS_REDIS_URL", "redis://localhost:6379/0")),
        artifact_backend="s3",
        artifact_s3_endpoint_url=os.environ["EVALOPS_TEST_MINIO_ENDPOINT"],
        artifact_s3_bucket=os.environ["EVALOPS_TEST_MINIO_BUCKET"],
        artifact_s3_prefix=f"agent-http-e2e/{uuid4().hex}",
        artifact_s3_access_key_id=SecretStr(os.environ["EVALOPS_TEST_MINIO_ACCESS_KEY"]),
        artifact_s3_secret_access_key=SecretStr(os.environ["EVALOPS_TEST_MINIO_SECRET_KEY"]),
        artifact_s3_addressing_style="path",
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
        otel_enabled=False,
    )


@pytest.mark.integration
async def test_agent_http_postgres_minio_auth_isolation_and_concurrent_idempotency() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")
    settings = _minio_settings(database_url)
    application = create_app(settings=settings)
    tenant_a_id, tenant_b_id = uuid4(), uuid4()
    generated_a, generated_b = generate_api_key(), generate_api_key()
    raw_a = generated_a.plaintext.get_secret_value()
    raw_b = generated_b.plaintext.get_secret_value()
    dataset_id, reference_id, version_id = uuid4(), uuid4(), uuid4()
    left_run_id, right_run_id = uuid4(), uuid4()
    left_job_id, right_job_id = uuid4(), uuid4()
    dataset_sha = hashlib.sha256(str(dataset_id).encode()).hexdigest()
    created_blob_shas = {dataset_sha}

    async with application.router.lifespan_context(application):
        session_factory = cast(AsyncSessionFactory, application.state.session_factory)
        real_store = cast(DeletableArtifactStore, application.state.artifact_store)
        store = InstrumentedArtifactStore(real_store)
        application.state.agent_artifact_service = SQLAlchemyAgentArtifactService(
            session_factory, artifact_store=store
        )
        application.state.review_service = SQLAlchemyReviewService(
            session_factory, artifact_store=store
        )
        try:
            async with session_factory.begin() as session:
                session.add_all(
                    [
                        Tenant(
                            id=tenant_a_id,
                            slug=f"agent-http-a-{tenant_a_id.hex}",
                            name="Agent HTTP A",
                        ),
                        Tenant(
                            id=tenant_b_id,
                            slug=f"agent-http-b-{tenant_b_id.hex}",
                            name="Agent HTTP B",
                        ),
                    ]
                )
                await session.flush()
                key_a = APIKey(
                    tenant_id=tenant_a_id,
                    name="agent-http-a",
                    key_prefix=generated_a.prefix,
                    key_hash=generated_a.key_hash,
                    can_review=True,
                    can_create_review_tasks=True,
                )
                key_b = APIKey(
                    tenant_id=tenant_b_id,
                    name="agent-http-b",
                    key_prefix=generated_b.prefix,
                    key_hash=generated_b.key_hash,
                    can_review=True,
                )
                session.add_all(
                    [
                        key_a,
                        key_b,
                        Dataset(id=dataset_id, tenant_id=tenant_a_id, name=f"d-{dataset_id.hex}"),
                        ArtifactBlob(
                            sha256=dataset_sha,
                            byte_size=1,
                            storage_path=f"{dataset_sha[:2]}/{dataset_sha}",
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    ArtifactReference(
                        id=reference_id,
                        tenant_id=tenant_a_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        blob_sha256=dataset_sha,
                        media_type="application/x-ndjson",
                    )
                )
                await session.flush()
                session.add(
                    DatasetVersion(
                        id=version_id,
                        dataset_id=dataset_id,
                        tenant_id=tenant_a_id,
                        artifact_id=reference_id,
                        version=1,
                        schema_version="1",
                        sha256=dataset_sha,
                        case_count=1,
                    )
                )
                await session.flush()
                for run_id, job_id, suffix in (
                    (left_run_id, left_job_id, "left"),
                    (right_run_id, right_job_id, "right"),
                ):
                    session.add(
                        EvaluationRun(
                            id=run_id,
                            tenant_id=tenant_a_id,
                            dataset_version_id=version_id,
                            dataset_hash=dataset_sha,
                            idempotency_key=f"agent-http-{suffix}-{run_id}",
                            request_hash="a" * 64,
                            target_type="mock",
                            target_config_json={},
                            target_config_hash="b" * 64,
                            evaluator_type="basic_answer",
                            evaluator_config_json={},
                            evaluator_config_hash="c" * 64,
                            target_version="v1",
                            evaluator_version="v1",
                            status=RunStatus.SUCCEEDED,
                            total_jobs=1,
                            succeeded_jobs=1,
                            created_by=key_a.id,
                        )
                    )
                    await session.flush()
                    session.add(
                        EvaluationJob(
                            id=job_id,
                            run_id=run_id,
                            case_id="case-1",
                            case_payload_json={"question": "safe?"},
                            status=JobStatus.SUCCEEDED,
                            max_attempts=1,
                        )
                    )
                    await session.flush()
                    session.add(
                        CaseResult(
                            job_id=job_id,
                            run_id=run_id,
                            tenant_id=tenant_a_id,
                            case_id="case-1",
                            answer_json={"answer": "yes"},
                            evidence_json={"citations": [], "sources": []},
                            metrics_json={},
                            latency_ms=1,
                        )
                    )

            transport = ASGITransport(app=application)
            headers_a = {"Authorization": f"Bearer {raw_a}"}
            headers_b = {"Authorization": f"Bearer {raw_b}"}
            left_payload = _artifact_payload(left_run_id, success=True, latency=100)
            right_payload = _artifact_payload(right_run_id, success=False, latency=150)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                uploads = await asyncio.gather(
                    *(
                        client.post(
                            f"/api/v1/runs/{left_run_id}/agent-artifacts",
                            headers=headers_a,
                            json=left_payload,
                        )
                        for _ in range(20)
                    )
                )
                assert {response.status_code for response in uploads} == {201}
                assert len({response.json()["id"] for response in uploads}) == 1
                left_artifact_id = UUID(uploads[0].json()["id"])
                created_blob_shas.add(uploads[0].json()["content_sha256"])

                right_upload = await client.post(
                    f"/api/v1/runs/{right_run_id}/agent-artifacts",
                    headers=headers_a,
                    json=right_payload,
                )
                assert right_upload.status_code == 201
                right_artifact_id = UUID(right_upload.json()["id"])
                created_blob_shas.add(right_upload.json()["content_sha256"])
                evaluation_payload = {"evaluators": _all_evaluators()}
                evaluations = await asyncio.gather(
                    *(
                        client.post(
                            f"/api/v1/runs/{left_run_id}/agent-artifacts/"
                            f"{left_artifact_id}/evaluations",
                            headers=headers_a,
                            json=evaluation_payload,
                        )
                        for _ in range(20)
                    )
                )
                assert {response.status_code for response in evaluations} == {200}
                assert (
                    len({tuple(item["id"] for item in response.json()) for response in evaluations})
                    == 1
                )
                right_evaluation = await client.post(
                    f"/api/v1/runs/{right_run_id}/agent-artifacts/{right_artifact_id}/evaluations",
                    headers=headers_a,
                    json=evaluation_payload,
                )
                assert right_evaluation.status_code == 200

                comparison = await client.post(
                    "/api/v1/agent-regression/compare",
                    headers=headers_a,
                    json={
                        "left_run_id": str(left_run_id),
                        "right_run_id": str(right_run_id),
                        "gate": {
                            "case_set_policy": "exact",
                            "minimum_metric_sample_count": 1,
                            "task_success_min": 1.0,
                            "allow_reported_evidence": True,
                        },
                    },
                )
                assert comparison.status_code == 200
                assert comparison.json()["gate_status"] == "failed"
                review = await client.post(
                    f"/api/v1/runs/{left_run_id}/review-tasks",
                    headers=headers_a,
                    json={"sample_size": 1, "source": "agent_artifact"},
                )
                assert review.status_code == 201
                assert review.json()[0]["evaluator_evidence_visible"] is False

                gets_before = store.get_count
                cross_artifact = await client.get(
                    f"/api/v1/runs/{left_run_id}/agent-artifacts/{left_artifact_id}",
                    headers=headers_b,
                )
                assert cross_artifact.status_code == 404
                assert store.get_count == gets_before
                cross_comparison = await client.post(
                    "/api/v1/agent-regression/compare",
                    headers=headers_b,
                    json={
                        "left_run_id": str(left_run_id),
                        "right_run_id": str(right_run_id),
                        "gate": {"case_set_policy": "exact"},
                    },
                )
                cross_review = await client.get(
                    "/api/v1/review-tasks",
                    headers=headers_b,
                    params={"run_id": str(left_run_id)},
                )
                assert cross_comparison.status_code == 404
                assert cross_review.status_code == 404
        finally:
            async with session_factory.begin() as session:
                # Pinned regression and review evidence uses RESTRICT semantics;
                # tear down that owned graph before deleting its tenant/runs.
                await session.execute(
                    delete(AgentRegressionEvidence).where(
                        AgentRegressionEvidence.tenant_id.in_((tenant_a_id, tenant_b_id))
                    )
                )
                await session.execute(
                    delete(AgentRegressionComparison).where(
                        AgentRegressionComparison.tenant_id.in_((tenant_a_id, tenant_b_id))
                    )
                )
                await session.execute(
                    delete(HumanReviewTask).where(
                        HumanReviewTask.tenant_id.in_((tenant_a_id, tenant_b_id))
                    )
                )
                await session.execute(
                    delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id)))
                )
            for sha256 in created_blob_shas - {dataset_sha}:
                async with session_factory() as session:
                    referenced = await session.scalar(
                        select(exists().where(ArtifactReference.blob_sha256 == sha256))
                    )
                if not referenced:
                    await store.delete_bytes(sha256)
            async with session_factory.begin() as session:
                await session.execute(
                    delete(ArtifactBlob).where(ArtifactBlob.sha256.in_(created_blob_shas))
                )


def _artifact_payload(run_id: UUID, *, success: bool, latency: int) -> dict[str, object]:
    return {
        "artifact": {
            "schema_version": "agent-run-artifact/v1",
            "run_id": str(run_id),
            "case_id": "case-1",
            "session_id": f"session-{run_id}",
            "framework": "custom-controller",
            "input": {"message": "safe?"},
            "output": {"answer": "yes", "task_success": success},
            "trajectory": [],
            "usage": {"latency_ms": latency},
            "terminal": {"state": "answer"},
        }
    }


def _all_evaluators() -> list[str]:
    return [
        "task_success",
        "tool_call_validity",
        "trajectory_efficiency",
        "grounding_citation",
        "permission_boundary",
        "terminal_state",
        "cost_latency",
    ]
