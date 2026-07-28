from typing import Literal, cast

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.health.service import ReadinessProbe, ReadinessReport

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


@router.get("/live", response_model=LivenessResponse)
async def get_liveness() -> LivenessResponse:
    """Report only whether the API process can serve requests."""
    return LivenessResponse(status="alive")


@router.get("/ready", response_model=ReadinessReport)
async def get_readiness(request: Request, response: Response) -> ReadinessReport:
    """Report whether the API's required infrastructure is usable."""
    probe = cast(ReadinessProbe, request.app.state.readiness_probe)
    report = await probe.check()
    if report.status == "not_ready":
        response.status_code = 503
    return report
