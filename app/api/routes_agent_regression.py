from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, Request

from app.agent_eval.schemas import AgentRegressionRequest, AgentRegressionResponse
from app.auth.dependencies import get_principal
from app.auth.principals import Principal


class AgentRegressionService(Protocol):
    async def compare(
        self,
        *,
        principal: Principal,
        request: AgentRegressionRequest,
    ) -> AgentRegressionResponse:
        """Compare tenant-scoped persisted Agent evidence and apply its configured gate."""


router = APIRouter(prefix="/api/v1/agent-regression", tags=["agent-regression"])


@router.post("/compare", response_model=AgentRegressionResponse)
async def compare_agent_runs(
    payload: AgentRegressionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> AgentRegressionResponse:
    service = cast(AgentRegressionService | None, request.app.state.agent_regression_service)
    if service is None:
        raise RuntimeError("agent regression service is not configured")
    return await service.compare(principal=principal, request=payload)
