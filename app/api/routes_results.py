from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.errors import APIError
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.domain.enums import JobStatus
from app.results.cursor import InvalidCursorError
from app.results.schemas import (
    ArtifactRead,
    CasePage,
    CaseQuery,
    CaseRead,
    MetricsRead,
    RunComparisonRead,
)
from app.results.service import CaseResultNotFoundError, ResultService

router = APIRouter(prefix="/api/v1/runs", tags=["results"])


@router.get("/compare", response_model=RunComparisonRead)
async def compare_runs(
    left_run_id: UUID,
    right_run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> RunComparisonRead:
    service = cast(ResultService | None, request.app.state.result_service)
    if service is None:
        raise RuntimeError("result service is not configured")
    return await service.compare_runs(
        principal=principal,
        left_run_id=left_run_id,
        right_run_id=right_run_id,
    )


@router.get("/{run_id}/metrics", response_model=MetricsRead)
async def get_run_metrics(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> MetricsRead:
    service = cast(ResultService | None, request.app.state.result_service)
    if service is None:
        raise RuntimeError("result service is not configured")
    return await service.get_metrics(principal=principal, run_id=run_id)


@router.post(
    "/{run_id}/artifacts",
    response_model=list[ArtifactRead],
    status_code=status.HTTP_201_CREATED,
)
async def generate_run_artifacts(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ArtifactRead]:
    service = cast(ResultService | None, request.app.state.result_service)
    if service is None:
        raise RuntimeError("result service is not configured")
    return await service.generate_artifacts(principal=principal, run_id=run_id)


@router.get("/{run_id}/cases", response_model=CasePage)
async def list_run_cases(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2_048)] = None,
    status: JobStatus | None = None,
    error_code: Annotated[
        str | None,
        Query(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$"),
    ] = None,
    sort: Literal["case_id", "latency", "metric"] = "case_id",
    metric_name: Annotated[
        str | None,
        Query(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
    ] = None,
    direction: Literal["asc", "desc"] = "asc",
) -> CasePage:
    service = cast(ResultService | None, request.app.state.result_service)
    if service is None:
        raise RuntimeError("result service is not configured")
    if (sort == "metric") != (metric_name is not None):
        raise APIError(
            status_code=422,
            code="invalid_request",
            message="metric_name must be provided if and only if sort=metric.",
        )
    query = CaseQuery(
        limit=limit,
        cursor=cursor,
        status=status,
        error_code=error_code,
        sort=sort,
        metric_name=metric_name,
        direction=direction,
    )
    try:
        return await service.list_cases(
            principal=principal,
            run_id=run_id,
            query=query,
        )
    except InvalidCursorError:
        raise APIError(
            status_code=422,
            code="invalid_cursor",
            message="The pagination cursor is invalid for this query.",
        ) from None


@router.get("/{run_id}/cases/{case_id}", response_model=CaseRead)
async def get_run_case(
    run_id: UUID,
    case_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> CaseRead:
    service = cast(ResultService | None, request.app.state.result_service)
    if service is None:
        raise RuntimeError("result service is not configured")
    try:
        return await service.get_case(
            principal=principal,
            run_id=run_id,
            case_id=case_id,
        )
    except CaseResultNotFoundError:
        raise APIError(
            status_code=404,
            code="case_result_not_found",
            message="The case result was not found.",
        ) from None
