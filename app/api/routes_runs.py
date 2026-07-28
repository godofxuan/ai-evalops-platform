from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.jobs.cancellation import CancellationService
from app.runs.schemas import RunCreate, RunRead
from app.runs.service import RunService

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: IdempotencyKey,
) -> RunRead:
    service = cast(RunService | None, request.app.state.run_service)
    if service is None:
        raise RuntimeError("run service is not configured")
    return await service.create_run(
        principal=principal,
        idempotency_key=idempotency_key,
        request=payload,
    )


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> RunRead:
    service = cast(RunService | None, request.app.state.run_service)
    if service is None:
        raise RuntimeError("run service is not configured")
    return await service.get_run(principal=principal, run_id=run_id)


@router.post(
    "/{run_id}/cancel",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_run(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> RunRead:
    service = cast(CancellationService | None, request.app.state.cancellation_service)
    if service is None:
        raise RuntimeError("cancellation service is not configured")
    return await service.cancel_run(principal=principal, run_id=run_id)
