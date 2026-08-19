from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.agent_eval.schemas import (
    AgentArtifactDetailRead,
    AgentArtifactEvaluationRequest,
    AgentArtifactEvaluationResultRead,
    AgentArtifactRead,
    AgentArtifactUpload,
)
from app.agent_eval.service import AgentArtifactNotFoundError, AgentArtifactRunMismatchError
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

    async def evaluate(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
        request: AgentArtifactEvaluationRequest,
    ) -> list[AgentArtifactEvaluationResultRead]:
        """Evaluate an authorized immutable Agent execution artifact."""

    async def get(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
    ) -> AgentArtifactDetailRead:
        """Read an authorized immutable Agent trajectory."""

    async def list_evaluations(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
    ) -> list[AgentArtifactEvaluationResultRead]:
        """List persisted evaluator evidence for an authorized artifact."""


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


@router.post(
    "/{run_id}/agent-artifacts/{artifact_id}/evaluations",
    response_model=list[AgentArtifactEvaluationResultRead],
)
async def evaluate_agent_artifact(
    run_id: UUID,
    artifact_id: UUID,
    payload: AgentArtifactEvaluationRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[AgentArtifactEvaluationResultRead]:
    service = cast(AgentArtifactService | None, request.app.state.agent_artifact_service)
    if service is None:
        raise RuntimeError("agent artifact service is not configured")
    try:
        return await service.evaluate(
            principal=principal,
            run_id=run_id,
            artifact_id=artifact_id,
            request=payload,
        )
    except AgentArtifactNotFoundError:
        raise APIError(
            status_code=404,
            code="agent_artifact_not_found",
            message="The Agent artifact was not found.",
        ) from None


@router.get(
    "/{run_id}/agent-artifacts/{artifact_id}",
    response_model=AgentArtifactDetailRead,
)
async def get_agent_artifact(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> AgentArtifactDetailRead:
    service = cast(AgentArtifactService | None, request.app.state.agent_artifact_service)
    if service is None:
        raise RuntimeError("agent artifact service is not configured")
    try:
        return await service.get(
            principal=principal,
            run_id=run_id,
            artifact_id=artifact_id,
        )
    except AgentArtifactNotFoundError:
        raise APIError(
            status_code=404,
            code="agent_artifact_not_found",
            message="The Agent artifact was not found.",
        ) from None


@router.get(
    "/{run_id}/agent-artifacts/{artifact_id}/evaluations",
    response_model=list[AgentArtifactEvaluationResultRead],
)
async def list_agent_artifact_evaluations(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[AgentArtifactEvaluationResultRead]:
    service = cast(AgentArtifactService | None, request.app.state.agent_artifact_service)
    if service is None:
        raise RuntimeError("agent artifact service is not configured")
    try:
        return await service.list_evaluations(
            principal=principal,
            run_id=run_id,
            artifact_id=artifact_id,
        )
    except AgentArtifactNotFoundError:
        raise APIError(
            status_code=404,
            code="agent_artifact_not_found",
            message="The Agent artifact was not found.",
        ) from None
