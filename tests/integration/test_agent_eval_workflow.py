import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from app.agent_eval.regression_service import SQLAlchemyAgentRegressionService
from app.agent_eval.schemas import (
    AgentArtifactEvaluationRequest,
    AgentArtifactUpload,
    AgentRegressionGateConfig,
    AgentRegressionRequest,
)
from app.agent_eval.service import AgentArtifactNotFoundError, SQLAlchemyAgentArtifactService
from app.artifacts.storage import LocalArtifactStore
from app.auth.principals import Principal
from app.core.config import Settings
from app.domain.enums import ArtifactType, JobStatus, RunStatus
from app.persistence.database import create_database_engine, create_session_factory
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
from app.reviews.service import SQLAlchemyReviewService


@pytest.mark.integration
async def test_real_postgresql_agent_evaluation_regression_and_review_workflow(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    artifact_store = LocalArtifactStore(tmp_path)
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    api_key_a_id = uuid4()
    api_key_b_id = uuid4()
    dataset_id = uuid4()
    dataset_reference_id = uuid4()
    dataset_version_id = uuid4()
    left_run_id = uuid4()
    right_run_id = uuid4()
    left_job_id = uuid4()
    right_job_id = uuid4()
    dataset_sha = hashlib.sha256(str(dataset_id).encode()).hexdigest()
    owned_blob_shas = {dataset_sha}
    principal_a = Principal(
        tenant_id=tenant_a_id,
        api_key_id=api_key_a_id,
        key_prefix=f"it_{api_key_a_id.hex[:12]}",
        can_create_review_tasks=True,
    )
    principal_b = Principal(
        tenant_id=tenant_b_id,
        api_key_id=api_key_b_id,
        key_prefix=f"it_{api_key_b_id.hex[:12]}",
    )

    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_a_id,
                        slug=f"agent-eval-a-{tenant_a_id.hex}",
                        name="Agent Eval Integration A",
                    ),
                    Tenant(
                        id=tenant_b_id,
                        slug=f"agent-eval-b-{tenant_b_id.hex}",
                        name="Agent Eval Integration B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=api_key_a_id,
                        tenant_id=tenant_a_id,
                        name="agent-eval-a",
                        key_prefix=principal_a.key_prefix,
                        key_hash="integration-only",
                        can_create_review_tasks=True,
                    ),
                    APIKey(
                        id=api_key_b_id,
                        tenant_id=tenant_b_id,
                        name="agent-eval-b",
                        key_prefix=principal_b.key_prefix,
                        key_hash="integration-only",
                    ),
                    Dataset(
                        id=dataset_id,
                        tenant_id=tenant_a_id,
                        name=f"agent-eval-{dataset_id.hex}",
                    ),
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
                    id=dataset_reference_id,
                    tenant_id=tenant_a_id,
                    artifact_type=ArtifactType.DATASET_SOURCE,
                    blob_sha256=dataset_sha,
                    media_type="application/x-ndjson",
                )
            )
            await session.flush()
            session.add(
                DatasetVersion(
                    id=dataset_version_id,
                    dataset_id=dataset_id,
                    tenant_id=tenant_a_id,
                    artifact_id=dataset_reference_id,
                    version=1,
                    schema_version="1",
                    sha256=dataset_sha,
                    case_count=1,
                )
            )
            await session.flush()
            for run_id, job_id, idempotency_key in (
                (left_run_id, left_job_id, "agent-left"),
                (right_run_id, right_job_id, "agent-right"),
            ):
                session.add(
                    EvaluationRun(
                        id=run_id,
                        tenant_id=tenant_a_id,
                        dataset_version_id=dataset_version_id,
                        dataset_hash=dataset_sha,
                        idempotency_key=f"{idempotency_key}-{run_id}",
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
                        created_by=api_key_a_id,
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

        artifact_service = SQLAlchemyAgentArtifactService(
            session_factory,
            artifact_store=artifact_store,
        )
        artifact_ids = []
        for run_id, success, latency in (
            (left_run_id, True, 100),
            (right_run_id, False, 150),
        ):
            uploaded = await artifact_service.ingest(
                principal=principal_a,
                run_id=run_id,
                request=AgentArtifactUpload.model_validate(
                    {
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
                ),
            )
            artifact_ids.append(uploaded.id)
            owned_blob_shas.add(uploaded.content_sha256)
            evaluation_request = AgentArtifactEvaluationRequest(
                evaluators=[
                    "task_success",
                    "tool_call_validity",
                    "trajectory_efficiency",
                    "grounding_citation",
                    "permission_boundary",
                    "terminal_state",
                    "cost_latency",
                ]
            )
            first = await artifact_service.evaluate(
                principal=principal_a,
                run_id=run_id,
                artifact_id=uploaded.id,
                request=evaluation_request,
            )
            replay = await artifact_service.evaluate(
                principal=principal_a,
                run_id=run_id,
                artifact_id=uploaded.id,
                request=evaluation_request,
            )
            assert len(first) == 7
            assert [item.id for item in replay] == [item.id for item in first]
            assert (
                len(
                    await artifact_service.list_evaluations(
                        principal=principal_a,
                        run_id=run_id,
                        artifact_id=uploaded.id,
                    )
                )
                == 7
            )

        detail = await artifact_service.get(
            principal=principal_a,
            run_id=left_run_id,
            artifact_id=artifact_ids[0],
        )
        assert detail.artifact.case_id == "case-1"
        with pytest.raises(AgentArtifactNotFoundError):
            await artifact_service.get(
                principal=principal_b,
                run_id=left_run_id,
                artifact_id=artifact_ids[0],
            )

        regression = await SQLAlchemyAgentRegressionService(session_factory).compare(
            principal=principal_a,
            request=AgentRegressionRequest(
                left_run_id=left_run_id,
                right_run_id=right_run_id,
                gate=AgentRegressionGateConfig(task_success_min=1.0),
            ),
        )
        assert regression.intersection_count == 1
        assert regression.gate_passed is False
        assert regression.gate_violations == ["task_success"]

        review_tasks = await SQLAlchemyReviewService(
            session_factory,
            artifact_store=artifact_store,
        ).create_tasks(
            principal=principal_a,
            run_id=left_run_id,
            sample_size=1,
            source="agent_artifact",
        )
        assert len(review_tasks) == 1
        encoded_packet = review_tasks[0].packet.model_dump(mode="json")
        assert encoded_packet["candidate_answer"] == "yes"
        assert "framework" not in str(encoded_packet)
        assert "session_id" not in str(encoded_packet)
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id))))
            await session.execute(
                delete(ArtifactBlob).where(ArtifactBlob.sha256.in_(owned_blob_shas))
            )
        await engine.dispose()
