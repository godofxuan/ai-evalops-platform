from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.agent_eval.schemas import AgentArtifactRead, AgentArtifactUpload
from app.agent_eval.service import AgentArtifactRunMismatchError
from app.api.errors import APIError
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.core.telemetry import Telemetry


class AgentArtifactService(Protocol):
    async def ingest(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        request: AgentArtifactUpload,
    ) -> AgentArtifactRead:
        """Persist or replay an immutable Agent execution artifact."""


router = APIRouter(prefix="/api/v1/runs", tags=["agent-artifacts"])


@router.post(
    "/{run_id}/agent-artifacts",
    response_model=AgentArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_agent_artifact(
    run_id: UUID,
    payload: AgentArtifactUpload,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> AgentArtifactRead:
    service = cast(AgentArtifactService | None, request.app.state.agent_artifact_service)
    if service is None:
        raise RuntimeError("agent artifact service is not configured")
    telemetry = cast(Telemetry, request.app.state.telemetry)
    artifact = payload.artifact
    with telemetry.start_as_current_span(
        "agent_artifact.ingest",
        attributes={
            "agent.session_id": artifact.session_id,
            "agent.framework": artifact.framework,
            "eval.run_id": str(run_id),
            "eval.case_id": artifact.case_id,
            "tenant_id": str(principal.tenant_id),
        },
    ):
        try:
            return await service.ingest(principal=principal, run_id=run_id, request=payload)
        except AgentArtifactRunMismatchError:
            raise APIError(
                status_code=422,
                code="invalid_agent_artifact",
                message="The Agent artifact does not match this Run or case.",
            ) from None
