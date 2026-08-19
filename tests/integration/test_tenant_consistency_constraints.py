import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.enums import ArtifactType
from app.persistence.database import (
    AsyncSessionFactory,
    create_database_engine,
    create_session_factory,
)
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
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
        idempotency_key=f"tenant-constraint-{run_id}",
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
        created_by=created_by,
    )


async def _assert_constraint_rejects(
    session_factory: AsyncSessionFactory,
    *,
    build_row: Callable[[], object],
    constraint_name: str,
) -> None:
    with pytest.raises(IntegrityError) as captured:
        async with session_factory.begin() as session:
            session.add(build_row())
            await session.flush()

    diagnostic = getattr(captured.value.orig, "diag", None)
    assert getattr(diagnostic, "constraint_name", None) == constraint_name


@pytest.mark.integration
async def test_real_postgresql_rejects_cross_tenant_and_cross_run_links(
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

    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    key_a_id = uuid4()
    key_b_id = uuid4()
    dataset_a_id = uuid4()
    dataset_b_id = uuid4()
    reference_a_id = uuid4()
    reference_b_id = uuid4()
    version_a_id = uuid4()
    version_b_id = uuid4()
    run_a1_id = uuid4()
    run_a2_id = uuid4()
    run_b_id = uuid4()
    job_a1_id = uuid4()
    job_a2_id = uuid4()
    job_b_id = uuid4()
    task_a_id = uuid4()
    blob_a_sha = _sha256(f"blob:{tenant_a_id}")
    blob_b_sha = _sha256(f"blob:{tenant_b_id}")
    shared_blob_sha = _sha256(f"invalid-reference:{tenant_a_id}")

    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_a_id,
                        slug=f"constraint-a-{tenant_a_id.hex}",
                        name="Tenant constraint A",
                    ),
                    Tenant(
                        id=tenant_b_id,
                        slug=f"constraint-b-{tenant_b_id.hex}",
                        name="Tenant constraint B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=key_a_id,
                        tenant_id=tenant_a_id,
                        name="tenant-constraint-key-a",
                        key_prefix=f"tca_{tenant_a_id.hex[:12]}",
                        key_hash="not-a-real-key",
                    ),
                    APIKey(
                        id=key_b_id,
                        tenant_id=tenant_b_id,
                        name="tenant-constraint-key-b",
                        key_prefix=f"tcb_{tenant_b_id.hex[:12]}",
                        key_hash="not-a-real-key",
                    ),
                    Dataset(
                        id=dataset_a_id,
                        tenant_id=tenant_a_id,
                        name=f"constraint-dataset-{tenant_a_id.hex}",
                    ),
                    Dataset(
                        id=dataset_b_id,
                        tenant_id=tenant_b_id,
                        name=f"constraint-dataset-{tenant_b_id.hex}",
                    ),
                    ArtifactBlob(
                        sha256=blob_a_sha,
                        byte_size=1,
                        storage_path=f"{blob_a_sha[:2]}/{blob_a_sha}",
                    ),
                    ArtifactBlob(
                        sha256=blob_b_sha,
                        byte_size=1,
                        storage_path=f"{blob_b_sha[:2]}/{blob_b_sha}",
                    ),
                    ArtifactBlob(
                        sha256=shared_blob_sha,
                        byte_size=1,
                        storage_path=f"{shared_blob_sha[:2]}/{shared_blob_sha}",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ArtifactReference(
                        id=reference_a_id,
                        blob_sha256=blob_a_sha,
                        tenant_id=tenant_a_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        media_type="application/x-ndjson",
                    ),
                    ArtifactReference(
                        id=reference_b_id,
                        blob_sha256=blob_b_sha,
                        tenant_id=tenant_b_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        media_type="application/x-ndjson",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    DatasetVersion(
                        id=version_a_id,
                        dataset_id=dataset_a_id,
                        tenant_id=tenant_a_id,
                        artifact_id=reference_a_id,
                        version=1,
                        sha256=blob_a_sha,
                        case_count=1,
                    ),
                    DatasetVersion(
                        id=version_b_id,
                        dataset_id=dataset_b_id,
                        tenant_id=tenant_b_id,
                        artifact_id=reference_b_id,
                        version=1,
                        sha256=blob_b_sha,
                        case_count=1,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    _run(
                        run_id=run_a1_id,
                        tenant_id=tenant_a_id,
                        dataset_version_id=version_a_id,
                        created_by=key_a_id,
                    ),
                    _run(
                        run_id=run_a2_id,
                        tenant_id=tenant_a_id,
                        dataset_version_id=version_a_id,
                        created_by=key_a_id,
                    ),
                    _run(
                        run_id=run_b_id,
                        tenant_id=tenant_b_id,
                        dataset_version_id=version_b_id,
                        created_by=key_b_id,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    EvaluationJob(
                        id=job_a1_id,
                        run_id=run_a1_id,
                        case_id="case-a1",
                        case_payload_json={},
                        max_attempts=1,
                    ),
                    EvaluationJob(
                        id=job_a2_id,
                        run_id=run_a2_id,
                        case_id="case-a2",
                        case_payload_json={},
                        max_attempts=1,
                    ),
                    EvaluationJob(
                        id=job_b_id,
                        run_id=run_b_id,
                        case_id="case-b",
                        case_payload_json={},
                        max_attempts=1,
                    ),
                ]
            )
            await session.flush()
            session.add(
                HumanReviewTask(
                    id=task_a_id,
                    tenant_id=tenant_a_id,
                    run_id=run_a1_id,
                    job_id=job_a1_id,
                    case_id="case-a1",
                    source_type="case_result",
                    source_record_id=uuid4(),
                    source_content_sha256="a" * 64,
                    packet_schema_version="review-packet/v1",
                    packet_sha256=_sha256("{}"),
                    evaluator_visibility_policy="after-submission-or-adjudication",
                    evaluator_evidence_json={},
                    packet_json={},
                    created_by=key_a_id,
                )
            )

        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: DatasetVersion(
                dataset_id=dataset_a_id,
                tenant_id=tenant_a_id,
                artifact_id=reference_b_id,
                version=2,
                sha256=_sha256("dataset-artifact-mismatch"),
                case_count=1,
            ),
            constraint_name=("fk_dataset_versions_artifact_id_tenant_id_artifact_references"),
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: DatasetVersion(
                dataset_id=dataset_b_id,
                tenant_id=tenant_a_id,
                artifact_id=reference_a_id,
                version=2,
                sha256=_sha256("dataset-tenant-mismatch"),
                case_count=1,
            ),
            constraint_name="fk_dataset_versions_dataset_id_tenant_id_datasets",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: _run(
                run_id=uuid4(),
                tenant_id=tenant_a_id,
                dataset_version_id=version_b_id,
                created_by=key_a_id,
            ),
            constraint_name="fk_evaluation_runs_dataset_version_tenant",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: _run(
                run_id=uuid4(),
                tenant_id=tenant_a_id,
                dataset_version_id=version_a_id,
                created_by=key_b_id,
            ),
            constraint_name="fk_evaluation_runs_created_by_tenant_id_api_keys",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: ArtifactReference(
                blob_sha256=shared_blob_sha,
                tenant_id=tenant_a_id,
                run_id=run_b_id,
                artifact_type=ArtifactType.SUMMARY_REPORT,
                media_type="application/json",
            ),
            constraint_name=("fk_artifact_references_run_id_tenant_id_evaluation_runs"),
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: CaseResult(
                job_id=job_a1_id,
                run_id=run_a2_id,
                tenant_id=tenant_a_id,
                case_id="case-result-wrong-run",
                answer_json={},
                evidence_json={},
                metrics_json={},
                latency_ms=1,
            ),
            constraint_name="fk_case_results_job_id_run_id_evaluation_jobs",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewTask(
                tenant_id=tenant_a_id,
                run_id=run_b_id,
                job_id=job_b_id,
                case_id="task-wrong-tenant",
                source_type="case_result",
                source_record_id=uuid4(),
                source_content_sha256="a" * 64,
                packet_schema_version="review-packet/v1",
                packet_sha256=_sha256("{}"),
                evaluator_visibility_policy="after-submission-or-adjudication",
                evaluator_evidence_json={},
                packet_json={},
                created_by=key_a_id,
            ),
            constraint_name="fk_human_review_tasks_run_id_tenant_id_evaluation_runs",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewTask(
                tenant_id=tenant_a_id,
                run_id=run_a1_id,
                job_id=job_a2_id,
                case_id="task-wrong-job-run",
                source_type="case_result",
                source_record_id=uuid4(),
                source_content_sha256="a" * 64,
                packet_schema_version="review-packet/v1",
                packet_sha256=_sha256("{}"),
                evaluator_visibility_policy="after-submission-or-adjudication",
                evaluator_evidence_json={},
                packet_json={},
                created_by=key_a_id,
            ),
            constraint_name="fk_human_review_tasks_job_id_run_id_evaluation_jobs",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewTask(
                tenant_id=tenant_a_id,
                run_id=run_a1_id,
                job_id=job_a1_id,
                case_id="task-wrong-creator",
                source_type="case_result",
                source_record_id=uuid4(),
                source_content_sha256="a" * 64,
                packet_schema_version="review-packet/v1",
                packet_sha256=_sha256("{}"),
                evaluator_visibility_policy="after-submission-or-adjudication",
                evaluator_evidence_json={},
                packet_json={},
                created_by=key_b_id,
            ),
            constraint_name="fk_human_review_tasks_created_by_tenant_id_api_keys",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewSubmission(
                tenant_id=tenant_b_id,
                task_id=task_a_id,
                reviewer_id=key_b_id,
                labels_json={},
            ),
            constraint_name="fk_human_review_submissions_task_tenant",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewSubmission(
                tenant_id=tenant_a_id,
                task_id=task_a_id,
                reviewer_id=key_b_id,
                labels_json={},
            ),
            constraint_name="fk_human_review_submissions_reviewer_tenant",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewAdjudication(
                tenant_id=tenant_b_id,
                task_id=task_a_id,
                adjudicator_id=key_b_id,
                labels_json={},
                rationale="cross-tenant task must be rejected",
            ),
            constraint_name="fk_human_review_adjudications_task_tenant",
        )
        await _assert_constraint_rejects(
            session_factory,
            build_row=lambda: HumanReviewAdjudication(
                tenant_id=tenant_a_id,
                task_id=task_a_id,
                adjudicator_id=key_b_id,
                labels_json={},
                rationale="cross-tenant adjudicator must be rejected",
            ),
            constraint_name="fk_human_review_adjudications_adjudicator_tenant",
        )
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(HumanReviewTask).where(HumanReviewTask.id == task_a_id))
            await session.execute(
                delete(EvaluationJob).where(EvaluationJob.id.in_((job_a1_id, job_a2_id, job_b_id)))
            )
            await session.execute(
                delete(EvaluationRun).where(EvaluationRun.id.in_((run_a1_id, run_a2_id, run_b_id)))
            )
            await session.execute(
                delete(DatasetVersion).where(DatasetVersion.id.in_((version_a_id, version_b_id)))
            )
            await session.execute(
                delete(ArtifactReference).where(
                    ArtifactReference.id.in_((reference_a_id, reference_b_id))
                )
            )
            await session.execute(
                delete(ArtifactBlob).where(
                    ArtifactBlob.sha256.in_((blob_a_sha, blob_b_sha, shared_blob_sha))
                )
            )
            await session.execute(
                delete(Dataset).where(Dataset.id.in_((dataset_a_id, dataset_b_id)))
            )
            await session.execute(delete(APIKey).where(APIKey.id.in_((key_a_id, key_b_id))))
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a_id, tenant_b_id))))
        await engine.dispose()
