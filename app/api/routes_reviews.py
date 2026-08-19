from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.reviews.schemas import (
    AdjudicateReview,
    CreateReviewTasks,
    ReviewAdjudicationRead,
    ReviewMetricsRead,
    ReviewSubmissionRead,
    ReviewTaskRead,
    SubmitReview,
)
from app.reviews.service import ReviewService

router = APIRouter(prefix="/api/v1", tags=["human-reviews"])


@router.post(
    "/runs/{run_id}/review-tasks",
    response_model=list[ReviewTaskRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_review_tasks(
    run_id: UUID,
    payload: CreateReviewTasks,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReviewTaskRead]:
    service = _service(request)
    return await service.create_tasks(
        principal=principal,
        run_id=run_id,
        sample_size=payload.sample_size,
        source=payload.source,
    )


@router.get("/review-tasks", response_model=list[ReviewTaskRead])
async def list_review_tasks(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReviewTaskRead]:
    return await _service(request).list_tasks(
        principal=principal,
        run_id=run_id,
    )


@router.post(
    "/review-tasks/{task_id}/submissions",
    response_model=ReviewSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    task_id: UUID,
    payload: SubmitReview,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewSubmissionRead:
    return await _service(request).submit_review(
        principal=principal,
        task_id=task_id,
        labels=payload.labels,
        comment=payload.comment,
    )


@router.post(
    "/review-tasks/{task_id}/adjudication",
    response_model=ReviewAdjudicationRead,
    status_code=status.HTTP_201_CREATED,
)
async def adjudicate_review(
    task_id: UUID,
    payload: AdjudicateReview,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewAdjudicationRead:
    return await _service(request).adjudicate(
        principal=principal,
        task_id=task_id,
        labels=payload.labels,
        rationale=payload.rationale,
    )


@router.get(
    "/runs/{run_id}/review-metrics",
    response_model=ReviewMetricsRead,
)
async def get_review_metrics(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewMetricsRead:
    return await _service(request).get_metrics(
        principal=principal,
        run_id=run_id,
    )


def _service(request: Request) -> ReviewService:
    service = cast(ReviewService | None, request.app.state.review_service)
    if service is None:
        raise RuntimeError("review service is not configured")
    return service
