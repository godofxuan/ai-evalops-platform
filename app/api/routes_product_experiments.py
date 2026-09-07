from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.product_experiments.service import ProductExperimentRead, ProductExperimentService

router = APIRouter(prefix="/api/v1/experiments", tags=["product-experiments"])


def _service(request: Request) -> ProductExperimentService:
    service = cast(ProductExperimentService | None, request.app.state.product_experiment_service)
    if service is None:
        raise RuntimeError("product experiment service is not configured")
    return service


@router.get("/{experiment_id}", response_model=ProductExperimentRead)
async def get_experiment(
    experiment_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProductExperimentRead:
    return await _service(request).get(principal=principal, experiment_id=experiment_id)


@router.post(
    "/{experiment_id}/cancel",
    response_model=ProductExperimentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_experiment(
    experiment_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProductExperimentRead:
    return await _service(request).cancel(principal=principal, experiment_id=experiment_id)
