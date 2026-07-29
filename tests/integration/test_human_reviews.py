import os
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    Artifact,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    HumanReviewAdjudication,
    HumanReviewSubmission,
    HumanReviewTask,
    Tenant,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_real_postgresql_blinded_double_review_and_third_adjudication(
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
    tenant_id = uuid4()
    creator_id = uuid4()
    reviewer_a_id = uuid4()
    reviewer_b_id = uuid4()
    adjudicator_id = uuid4()
    dataset_id = uuid4()
    artifact_id = uuid4()
    version_id = uuid4()
    run_id = uuid4()
    creator_key = generate_api_key()
    reviewer_a_key = generate_api_key()
    reviewer_b_key = generate_api_key()
    adjudicator_key = generate_api_key()
    application = create_app(settings=settings)

    async with application.router.lifespan_context(application):
        session_factory = cast(AsyncSessionFactory, application.state.session_factory)
        async with session_factory.begin() as session:
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=f"review-integration-{uuid4().hex}",
                    name="Review integration tenant",
                )
            )
            session.add_all(
                [
                    APIKey(
                        id=creator_id,
                        tenant_id=tenant_id,
                        name="creator",
                        key_prefix=creator_key.key_prefix,
                        key_hash=creator_key.key_hash,
                        can_review=False,
                    ),
                    APIKey(
                        id=reviewer_a_id,
                        tenant_id=tenant_id,
                        name="reviewer-a",
                        key_prefix=reviewer_a_key.key_prefix,
                        key_hash=reviewer_a_key.key_hash,
                        can_review=True,
                    ),
                    APIKey(
                        id=reviewer_b_id,
                        tenant_id=tenant_id,
                        name="reviewer-b",
                        key_prefix=reviewer_b_key.key_prefix,
                        key_hash=reviewer_b_key.key_hash,
                        can_review=True,
                    ),
                    APIKey(
                        id=adjudicator_id,
                        tenant_id=tenant_id,
                        name="adjudicator",
                        key_prefix=adjudicator_key.key_prefix,
                        key_hash=adjudicator_key.key_hash,
                        can_review=True,
                    ),
                ]
            )
            dataset = Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name=f"review-dataset-{uuid4().hex}",
            )
            artifact = Artifact(
                id=artifact_id,
                tenant_id=tenant_id,
                artifact_type=ArtifactType.DATASET_SOURCE,
                sha256="a" * 64,
                media_type="application/x-ndjson",
                byte_size=1,
                storage_path="aa/" + "a" * 64,
            )
            session.add_all([dataset, artifact])
            await session.flush()
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    artifact_id=artifact_id,
                    version=1,
                    schema_version="1",
                    sha256="a" * 64,
                    case_count=2,
                )
            )
            await session.flush()
            session.add(
                EvaluationRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    dataset_version_id=version_id,
                    dataset_hash="a" * 64,
                    idempotency_key=f"review-{uuid4().hex}",
                    request_hash="b" * 64,
                    target_type="mock",
                    target_config_json={},
                    target_config_hash="c" * 64,
                    evaluator_type="basic_answer",
                    evaluator_config_json={},
                    evaluator_config_hash="d" * 64,
                    target_version="v1",
                    evaluator_version="v1",
                    status=RunStatus.SUCCEEDED,
                    total_jobs=2,
                    succeeded_jobs=2,
                    failed_jobs=0,
                    cancelled_jobs=0,
                    created_by=creator_id,
                    version=1,
                )
            )
            await session.flush()
            for index in (1, 2):
                job_id = uuid4()
                session.add(
                    EvaluationJob(
                        id=job_id,
                        run_id=run_id,
                        case_id=f"case-{index}",
                        case_payload_json={
                            "case_id": f"case-{index}",
                            "question": f"question-{index}",
                            "expected_answer": f"reference-{index}",
                            "metadata": {},
                        },
                        status=JobStatus.SUCCEEDED,
                        attempt_count=1,
                        max_attempts=3,
                        version=2,
                    )
                )
                await session.flush()
                session.add(
                    CaseResult(
                        job_id=job_id,
                        run_id=run_id,
                        case_id=f"case-{index}",
                        answer_json={"answer": f"candidate-{index}"},
                        evidence_json={"citations": [], "sources": []},
                        metrics_json={"machine_score": 0.99},
                        latency_ms=10,
                    )
                )

        def headers(key: object) -> dict[str, str]:
            generated = cast(type(creator_key), key)
            return {"Authorization": (f"Bearer {generated.plaintext.get_secret_value()}")}

        labels_a = {
            "retrieval_relevance": 4,
            "answer_correctness": 5,
            "answer_completeness": 4,
            "citation_support": 3,
            "refusal_appropriateness": None,
        }
        labels_disputed = labels_a | {"answer_correctness": 2}
        try:
            async with AsyncClient(
                transport=ASGITransport(app=application),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    f"/api/v1/runs/{run_id}/review-tasks",
                    headers=headers(creator_key),
                    json={"sample_size": 2},
                )
                assert created.status_code == 201
                assert len(created.json()) == 2
                assert "machine_score" not in created.text
                task_ids = [UUID(item["id"]) for item in created.json()]
                async with session_factory() as session:
                    packet_artifacts = await session.scalar(
                        select(func.count(Artifact.id)).where(
                            Artifact.run_id == run_id,
                            Artifact.artifact_type == ArtifactType.HUMAN_REVIEW_PACKET,
                        )
                    )
                assert packet_artifacts == 1

                ordinary_submit = await client.post(
                    f"/api/v1/review-tasks/{task_ids[0]}/submissions",
                    headers=headers(creator_key),
                    json={"labels": labels_a},
                )
                assert ordinary_submit.status_code == 403

                for task_id in task_ids:
                    first = await client.post(
                        f"/api/v1/review-tasks/{task_id}/submissions",
                        headers=headers(reviewer_a_key),
                        json={"labels": labels_a},
                    )
                    assert first.status_code == 201
                second_agreed = await client.post(
                    f"/api/v1/review-tasks/{task_ids[0]}/submissions",
                    headers=headers(reviewer_b_key),
                    json={"labels": labels_a},
                )
                second_disputed = await client.post(
                    f"/api/v1/review-tasks/{task_ids[1]}/submissions",
                    headers=headers(reviewer_b_key),
                    json={"labels": labels_disputed},
                )
                assert second_agreed.status_code == 201
                assert second_disputed.status_code == 201

                overwrite = await client.post(
                    f"/api/v1/review-tasks/{task_ids[1]}/submissions",
                    headers=headers(reviewer_b_key),
                    json={"labels": labels_a},
                )
                assert overwrite.status_code == 409

                own_a = await client.get(
                    "/api/v1/review-tasks",
                    headers=headers(reviewer_a_key),
                    params={"run_id": str(run_id)},
                )
                own_b = await client.get(
                    "/api/v1/review-tasks",
                    headers=headers(reviewer_b_key),
                    params={"run_id": str(run_id)},
                )
                assert own_a.status_code == own_b.status_code == 200
                assert all(item["own_submission"] for item in own_a.json())
                assert "reviewer_id" not in own_a.text
                assert "machine_score" not in own_a.text

                reviewer_cannot_adjudicate = await client.post(
                    f"/api/v1/review-tasks/{task_ids[1]}/adjudication",
                    headers=headers(reviewer_a_key),
                    json={"labels": labels_a, "rationale": "resolve"},
                )
                assert reviewer_cannot_adjudicate.status_code == 409
                adjudicated = await client.post(
                    f"/api/v1/review-tasks/{task_ids[1]}/adjudication",
                    headers=headers(adjudicator_key),
                    json={"labels": labels_a, "rationale": "third reviewer decision"},
                )
                assert adjudicated.status_code == 201

                metrics = await client.get(
                    f"/api/v1/runs/{run_id}/review-metrics",
                    headers=headers(creator_key),
                )
                assert metrics.status_code == 200
                assert metrics.json()["paired_tasks"] == 2
                assert metrics.json()["adjudicated_tasks"] == 1
                assert metrics.json()["paired_labels"] == 8
        finally:
            async with session_factory.begin() as session:
                await session.execute(
                    delete(HumanReviewAdjudication).where(
                        HumanReviewAdjudication.tenant_id == tenant_id
                    )
                )
                await session.execute(
                    delete(HumanReviewSubmission).where(
                        HumanReviewSubmission.tenant_id == tenant_id
                    )
                )
                await session.execute(
                    delete(HumanReviewTask).where(HumanReviewTask.tenant_id == tenant_id)
                )
                await session.execute(delete(CaseResult).where(CaseResult.run_id == run_id))
                await session.execute(delete(EvaluationJob).where(EvaluationJob.run_id == run_id))
                await session.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
                await session.execute(delete(DatasetVersion).where(DatasetVersion.id == version_id))
                await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
                await session.execute(delete(Artifact).where(Artifact.id == artifact_id))
                await session.execute(delete(APIKey).where(APIKey.tenant_id == tenant_id))
                await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
