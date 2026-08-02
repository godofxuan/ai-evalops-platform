import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.repository import ensure_artifact_reference
from app.artifacts.storage import ArtifactStore, StoredArtifact
from app.auth.principals import Principal
from app.domain.enums import ArtifactType, JobStatus, ReviewTaskStatus
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AuditEvent,
    CaseResult,
    EvaluationJob,
    EvaluationRun,
    HumanReviewAdjudication,
    HumanReviewSubmission,
    HumanReviewTask,
)
from app.reviews.agreement import calculate_agreement
from app.reviews.schemas import (
    ReviewAdjudicationRead,
    ReviewLabels,
    ReviewMetricsRead,
    ReviewPacket,
    ReviewSubmissionRead,
    ReviewTaskRead,
)


class ReviewPermissionError(Exception):
    """The authenticated credential is not designated for human review."""


class ReviewTaskCreationPermissionError(Exception):
    """The credential cannot create or expand human review tasks."""


class ReviewNotFoundError(Exception):
    """Hide absent and cross-tenant review resources."""


class ReviewConflictError(Exception):
    """The immutable review workflow cannot accept the requested transition."""


class ReviewService(Protocol):
    async def create_tasks(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        sample_size: int,
    ) -> list[ReviewTaskRead]:
        """Create or return deterministic blinded review tasks."""

    async def list_tasks(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ReviewTaskRead]:
        """Return packets plus only the current reviewer's own submission."""

    async def submit_review(
        self,
        *,
        principal: Principal,
        task_id: UUID,
        labels: ReviewLabels,
        comment: str | None,
    ) -> ReviewSubmissionRead:
        """Append one immutable reviewer submission."""

    async def adjudicate(
        self,
        *,
        principal: Principal,
        task_id: UUID,
        labels: ReviewLabels,
        rationale: str,
    ) -> ReviewAdjudicationRead:
        """Append a third-reviewer adjudication for a disputed task."""

    async def get_metrics(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> ReviewMetricsRead:
        """Return agreement without exposing individual reviewers."""


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    job_id: UUID
    case_id: str
    case_payload: dict[str, object]
    answer: dict[str, object]
    evidence: dict[str, object]


def build_review_candidates_statement(
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> Select[tuple[UUID, str, dict[str, object], dict[str, object], dict[str, object]]]:
    return (
        select(
            EvaluationJob.id,
            EvaluationJob.case_id,
            EvaluationJob.case_payload_json,
            CaseResult.answer_json,
            CaseResult.evidence_json,
        )
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .join(CaseResult, CaseResult.job_id == EvaluationJob.id)
        .where(
            EvaluationRun.tenant_id == tenant_id,
            EvaluationJob.run_id == run_id,
            EvaluationJob.status == JobStatus.SUCCEEDED,
        )
    )


def build_reviewer_tasks_statement(
    *,
    tenant_id: UUID,
    run_id: UUID,
    reviewer_id: UUID,
) -> Select[Any]:
    return (
        select(HumanReviewTask, HumanReviewSubmission)
        .outerjoin(
            HumanReviewSubmission,
            and_(
                HumanReviewSubmission.task_id == HumanReviewTask.id,
                HumanReviewSubmission.reviewer_id == reviewer_id,
            ),
        )
        .where(
            HumanReviewTask.tenant_id == tenant_id,
            HumanReviewTask.run_id == run_id,
        )
        .order_by(HumanReviewTask.created_at.asc(), HumanReviewTask.id.asc())
    )


def build_lock_review_task_statement(
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> Select[tuple[HumanReviewTask]]:
    return (
        select(HumanReviewTask)
        .where(
            HumanReviewTask.id == task_id,
            HumanReviewTask.tenant_id == tenant_id,
        )
        .with_for_update()
    )


class SQLAlchemyReviewService:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store

    async def create_tasks(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        sample_size: int,
    ) -> list[ReviewTaskRead]:
        _require_task_creator(principal)
        async with self._session_factory.begin() as session:
            await _require_run(
                session,
                tenant_id=principal.tenant_id,
                run_id=run_id,
            )
            rows = (
                await session.execute(
                    build_review_candidates_statement(
                        tenant_id=principal.tenant_id,
                        run_id=run_id,
                    )
                )
            ).all()
            candidates = [
                ReviewCandidate(
                    job_id=job_id,
                    case_id=case_id,
                    case_payload=dict(case_payload),
                    answer=dict(answer),
                    evidence=dict(evidence),
                )
                for job_id, case_id, case_payload, answer, evidence in rows
            ]
            selected = sorted(
                candidates,
                key=lambda item: hashlib.sha256(f"{run_id}:{item.case_id}".encode()).digest(),
            )[:sample_size]
            for item in selected:
                task_id = uuid4()
                await session.execute(
                    postgresql_insert(HumanReviewTask)
                    .values(
                        id=task_id,
                        tenant_id=principal.tenant_id,
                        run_id=run_id,
                        job_id=item.job_id,
                        case_id=item.case_id,
                        packet_json=_packet(item).model_dump(mode="json"),
                        status=ReviewTaskStatus.OPEN,
                        created_by=principal.api_key_id,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_human_review_tasks_run_id_case_id",
                    )
                )
            tasks = (
                (
                    await session.execute(
                        select(HumanReviewTask)
                        .where(
                            HumanReviewTask.tenant_id == principal.tenant_id,
                            HumanReviewTask.run_id == run_id,
                        )
                        .order_by(
                            HumanReviewTask.created_at.asc(),
                            HumanReviewTask.id.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
        task_reads = [_task_read(task, own_submission=None) for task in tasks]
        if self._artifact_store is not None:
            stored = await self._artifact_store.put_bytes(
                serialize_review_packet_artifact(run_id, task_reads)
            )
            async with self._session_factory.begin() as session:
                await _ensure_packet_artifact(
                    session,
                    tenant_id=principal.tenant_id,
                    run_id=run_id,
                    stored=stored,
                )
        return task_reads

    async def list_tasks(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ReviewTaskRead]:
        _require_reviewer(principal)
        async with self._session_factory() as session:
            await _require_run(
                session,
                tenant_id=principal.tenant_id,
                run_id=run_id,
            )
            rows = (
                await session.execute(
                    build_reviewer_tasks_statement(
                        tenant_id=principal.tenant_id,
                        run_id=run_id,
                        reviewer_id=principal.api_key_id,
                    )
                )
            ).all()
        return [_task_read(task, own_submission=submission) for task, submission in rows]

    async def submit_review(
        self,
        *,
        principal: Principal,
        task_id: UUID,
        labels: ReviewLabels,
        comment: str | None,
    ) -> ReviewSubmissionRead:
        _require_reviewer(principal)
        async with self._session_factory.begin() as session:
            task = await _lock_task(
                session,
                tenant_id=principal.tenant_id,
                task_id=task_id,
            )
            if task.status is not ReviewTaskStatus.OPEN:
                raise ReviewConflictError
            submissions = (
                (
                    await session.execute(
                        select(HumanReviewSubmission)
                        .where(HumanReviewSubmission.task_id == task.id)
                        .order_by(
                            HumanReviewSubmission.created_at.asc(),
                            HumanReviewSubmission.id.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if any(item.reviewer_id == principal.api_key_id for item in submissions):
                raise ReviewConflictError
            if len(submissions) >= 2:
                raise ReviewConflictError
            submission = HumanReviewSubmission(
                tenant_id=principal.tenant_id,
                task_id=task.id,
                reviewer_id=principal.api_key_id,
                labels_json=labels.model_dump(mode="json"),
                comment=comment,
            )
            session.add(submission)
            await session.flush()
            if len(submissions) == 1:
                first = ReviewLabels.model_validate(submissions[0].labels_json)
                task.status = resolve_second_review(first, labels)
            session.add(
                AuditEvent(
                    tenant_id=principal.tenant_id,
                    actor_id=str(principal.api_key_id),
                    action="human_review.submitted",
                    resource_type="human_review_task",
                    resource_id=task.id,
                    metadata_json={
                        "submission_id": str(submission.id),
                        "task_status": task.status.value,
                    },
                )
            )
        return _submission_read(submission)

    async def adjudicate(
        self,
        *,
        principal: Principal,
        task_id: UUID,
        labels: ReviewLabels,
        rationale: str,
    ) -> ReviewAdjudicationRead:
        _require_reviewer(principal)
        async with self._session_factory.begin() as session:
            task = await _lock_task(
                session,
                tenant_id=principal.tenant_id,
                task_id=task_id,
            )
            if task.status is not ReviewTaskStatus.DISPUTED:
                raise ReviewConflictError
            reviewer_ids = set(
                (
                    await session.execute(
                        select(HumanReviewSubmission.reviewer_id).where(
                            HumanReviewSubmission.task_id == task.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(reviewer_ids) != 2 or principal.api_key_id in reviewer_ids:
                raise ReviewConflictError
            existing = await session.scalar(
                select(HumanReviewAdjudication.id).where(HumanReviewAdjudication.task_id == task.id)
            )
            if existing is not None:
                raise ReviewConflictError
            adjudication = HumanReviewAdjudication(
                tenant_id=principal.tenant_id,
                task_id=task.id,
                adjudicator_id=principal.api_key_id,
                labels_json=labels.model_dump(mode="json"),
                rationale=rationale,
            )
            session.add(adjudication)
            task.status = ReviewTaskStatus.ADJUDICATED
            await session.flush()
            session.add(
                AuditEvent(
                    tenant_id=principal.tenant_id,
                    actor_id=str(principal.api_key_id),
                    action="human_review.adjudicated",
                    resource_type="human_review_task",
                    resource_id=task.id,
                    metadata_json={"adjudication_id": str(adjudication.id)},
                )
            )
        return _adjudication_read(adjudication)

    async def get_metrics(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> ReviewMetricsRead:
        async with self._session_factory() as session:
            await _require_run(
                session,
                tenant_id=principal.tenant_id,
                run_id=run_id,
            )
            rows = (
                await session.execute(
                    select(HumanReviewTask, HumanReviewSubmission)
                    .outerjoin(
                        HumanReviewSubmission,
                        HumanReviewSubmission.task_id == HumanReviewTask.id,
                    )
                    .where(
                        HumanReviewTask.tenant_id == principal.tenant_id,
                        HumanReviewTask.run_id == run_id,
                    )
                    .order_by(
                        HumanReviewTask.id.asc(),
                        HumanReviewSubmission.created_at.asc(),
                        HumanReviewSubmission.id.asc(),
                    )
                )
            ).all()
        tasks: dict[UUID, HumanReviewTask] = {}
        submissions: defaultdict[UUID, list[HumanReviewSubmission]] = defaultdict(list)
        for task, submission in rows:
            tasks[task.id] = task
            if submission is not None:
                submissions[task.id].append(submission)
        label_pairs: list[tuple[int, int]] = []
        paired_tasks = 0
        for _task_id, task_submissions in submissions.items():
            if len(task_submissions) != 2:
                continue
            paired_tasks += 1
            first = ReviewLabels.model_validate(task_submissions[0].labels_json)
            second = ReviewLabels.model_validate(task_submissions[1].labels_json)
            first_values = first.model_dump()
            second_values = second.model_dump()
            for dimension in first_values:
                left = first_values[dimension]
                right = second_values[dimension]
                if isinstance(left, int) and isinstance(right, int):
                    label_pairs.append((left, right))
        agreement = calculate_agreement(label_pairs)
        statuses = [task.status for task in tasks.values()]
        return ReviewMetricsRead(
            run_id=run_id,
            task_count=len(tasks),
            paired_tasks=paired_tasks,
            agreed_tasks=statuses.count(ReviewTaskStatus.AGREED),
            disputed_tasks=statuses.count(ReviewTaskStatus.DISPUTED),
            adjudicated_tasks=statuses.count(ReviewTaskStatus.ADJUDICATED),
            paired_labels=agreement.paired_labels,
            exact_agreement=agreement.exact_agreement,
            cohen_kappa=agreement.cohen_kappa,
        )


def resolve_second_review(
    first: ReviewLabels,
    second: ReviewLabels,
) -> ReviewTaskStatus:
    return (
        ReviewTaskStatus.AGREED
        if first.model_dump(mode="json") == second.model_dump(mode="json")
        else ReviewTaskStatus.DISPUTED
    )


def serialize_review_packet_artifact(
    run_id: UUID,
    tasks: list[ReviewTaskRead],
) -> bytes:
    return json.dumps(
        {
            "schema_version": "1",
            "run_id": str(run_id),
            "packets": [
                task.packet.model_dump(mode="json")
                for task in sorted(tasks, key=lambda item: item.case_id)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_reviewer(principal: Principal) -> None:
    if not principal.can_review:
        raise ReviewPermissionError


def _require_task_creator(principal: Principal) -> None:
    if not principal.can_create_review_tasks:
        raise ReviewTaskCreationPermissionError


async def _require_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> None:
    run_exists = await session.scalar(
        select(EvaluationRun.id).where(
            EvaluationRun.id == run_id,
            EvaluationRun.tenant_id == tenant_id,
        )
    )
    if run_exists is None:
        raise ReviewNotFoundError


async def _lock_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> HumanReviewTask:
    task = (
        await session.execute(
            build_lock_review_task_statement(
                tenant_id=tenant_id,
                task_id=task_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise ReviewNotFoundError
    return task


async def _ensure_packet_artifact(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
    stored: StoredArtifact,
) -> None:
    await ensure_artifact_reference(
        session,
        tenant_id=tenant_id,
        run_id=run_id,
        artifact_type=ArtifactType.HUMAN_REVIEW_PACKET,
        media_type="application/json",
        stored=stored,
    )


def _packet(candidate: ReviewCandidate) -> ReviewPacket:
    return ReviewPacket(
        case_id=candidate.case_id,
        question=str(candidate.case_payload.get("question", "")),
        reference_answer=candidate.case_payload.get("expected_answer"),
        candidate_answer=candidate.answer.get("answer"),
        citations=_json_list(candidate.evidence.get("citations")),
        sources=_json_list(candidate.evidence.get("sources")),
    )


def _json_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _task_read(
    task: HumanReviewTask,
    *,
    own_submission: HumanReviewSubmission | None,
) -> ReviewTaskRead:
    return ReviewTaskRead(
        id=task.id,
        run_id=task.run_id,
        case_id=task.case_id,
        status=task.status,
        packet=ReviewPacket.model_validate(task.packet_json),
        own_submission=(None if own_submission is None else _submission_read(own_submission)),
        created_at=task.created_at,
    )


def _submission_read(submission: HumanReviewSubmission) -> ReviewSubmissionRead:
    return ReviewSubmissionRead(
        id=submission.id,
        task_id=submission.task_id,
        labels=ReviewLabels.model_validate(submission.labels_json),
        comment=submission.comment,
        created_at=submission.created_at,
    )


def _adjudication_read(
    adjudication: HumanReviewAdjudication,
) -> ReviewAdjudicationRead:
    return ReviewAdjudicationRead(
        id=adjudication.id,
        task_id=adjudication.task_id,
        labels=ReviewLabels.model_validate(adjudication.labels_json),
        rationale=adjudication.rationale,
        created_at=adjudication.created_at,
    )
