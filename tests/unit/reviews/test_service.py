from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.auth.principals import Principal
from app.domain.enums import ReviewTaskStatus
from app.reviews.schemas import ReviewLabels, ReviewPacket, ReviewTaskRead
from app.reviews.service import (
    ReviewPermissionError,
    ReviewTaskCreationPermissionError,
    SQLAlchemyReviewService,
    build_lock_review_task_statement,
    build_review_candidates_statement,
    build_reviewer_tasks_statement,
    resolve_second_review,
    serialize_review_packet_artifact,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
TASK_ID = UUID("00000000-0000-0000-0000-000000000b01")


def _labels(correctness: int) -> ReviewLabels:
    return ReviewLabels(
        retrieval_relevance=4,
        answer_correctness=correctness,
        answer_completeness=4,
        citation_support=3,
        refusal_appropriateness=None,
    )


async def test_service_rejects_ordinary_api_key_before_database_access() -> None:
    service = SQLAlchemyReviewService(None)  # type: ignore[arg-type]
    principal = Principal(
        tenant_id=TENANT_ID,
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
        can_review=False,
    )

    with pytest.raises(ReviewPermissionError):
        await service.submit_review(
            principal=principal,
            task_id=TASK_ID,
            labels=_labels(5),
            comment=None,
        )


async def test_reviewer_cannot_create_tasks_without_creator_permission() -> None:
    service = SQLAlchemyReviewService(None)  # type: ignore[arg-type]
    reviewer = Principal(
        tenant_id=TENANT_ID,
        api_key_id=UUID("00000000-0000-0000-0000-000000000111"),
        key_prefix="evk_111122334455",
        can_review=True,
    )

    with pytest.raises(ReviewTaskCreationPermissionError):
        await service.create_tasks(
            principal=reviewer,
            run_id=UUID("00000000-0000-0000-0000-000000000601"),
            sample_size=20,
        )


def test_second_review_becomes_agreed_or_disputed_without_overwriting_labels() -> None:
    first = _labels(5)

    assert resolve_second_review(first, _labels(5)) is ReviewTaskStatus.AGREED
    assert resolve_second_review(first, _labels(2)) is ReviewTaskStatus.DISPUTED


def test_review_queries_are_tenant_scoped_blind_and_only_join_own_submission() -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000601")
    reviewer_id = UUID("00000000-0000-0000-0000-000000000111")
    candidate_sql = str(
        build_review_candidates_statement(
            tenant_id=TENANT_ID,
            run_id=run_id,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    task_sql = str(
        build_reviewer_tasks_statement(
            tenant_id=TENANT_ID,
            run_id=run_id,
            reviewer_id=reviewer_id,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert f"evaluation_runs.tenant_id = '{TENANT_ID}'" in candidate_sql
    assert "case_results.metrics_json" not in candidate_sql
    assert f"human_review_submissions.reviewer_id = '{reviewer_id}'" in task_sql
    assert f"human_review_tasks.tenant_id = '{TENANT_ID}'" in task_sql


def test_submission_and_adjudication_serialize_on_tenant_scoped_task_row() -> None:
    sql = str(
        build_lock_review_task_statement(
            tenant_id=TENANT_ID,
            task_id=TASK_ID,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert f"human_review_tasks.tenant_id = '{TENANT_ID}'" in sql
    assert f"human_review_tasks.id = '{TASK_ID}'" in sql
    assert "FOR UPDATE" in sql


def test_review_packet_artifact_contains_only_blinded_packets() -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000601")
    content = serialize_review_packet_artifact(
        run_id,
        [
            ReviewTaskRead(
                id=TASK_ID,
                run_id=run_id,
                case_id="case-1",
                status=ReviewTaskStatus.OPEN,
                packet=ReviewPacket(
                    case_id="case-1",
                    question="q",
                    reference_answer="reference",
                    candidate_answer="candidate",
                    citations=[],
                    sources=[],
                ),
                own_submission=None,
                created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            )
        ],
    )

    assert b'"run_id":"00000000-0000-0000-0000-000000000601"' in content
    assert b'"candidate_answer":"candidate"' in content
    assert b"metrics" not in content
    assert b"submission" not in content
    assert b"reviewer" not in content
