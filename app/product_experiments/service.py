"""Tenant-authenticated product controls over existing durable Runs."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.auth.principals import Principal
from app.domain.enums import RunStatus
from app.product_experiments.persistence import SQLAlchemyProductExperimentRepository
from app.runs.schemas import RunRead
from app.runs.service import RunNotFoundError, RunService

ProductState = Literal[
    "QUEUED", "RUNNING", "CANCELLING", "CANCELLED", "EXECUTION_FAILED", "READY_FOR_ASSESSMENT"
]


class ExperimentSubmissionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    baseline_run_id: UUID
    candidate_run_id: UUID
    status_url: str
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False


class ProductExperimentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    state: ProductState
    cancel_requested: bool
    baseline: RunRead
    candidate: RunRead
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False


class ProductExperimentService:
    def __init__(
        self, repository: SQLAlchemyProductExperimentRepository, run_service: RunService
    ) -> None:
        self._repository = repository
        self._run_service = run_service

    async def get(self, *, principal: Principal, experiment_id: UUID) -> ProductExperimentRead:
        experiment = await self._repository.get(
            tenant_id=principal.tenant_id, experiment_id=experiment_id
        )
        if experiment is None:
            raise RunNotFoundError
        baseline = await self._run_service.get_run(
            principal=principal, run_id=experiment.baseline_run_id
        )
        candidate = await self._run_service.get_run(
            principal=principal, run_id=experiment.candidate_run_id
        )
        states = {baseline.status, candidate.status}
        terminal = {
            RunStatus.SUCCEEDED,
            RunStatus.PARTIALLY_SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
        state: ProductState
        if states <= terminal:
            if experiment.cancel_requested and RunStatus.CANCELLED in states:
                state = "CANCELLED"
            elif states == {RunStatus.SUCCEEDED}:
                state = "READY_FOR_ASSESSMENT"
            else:
                state = "EXECUTION_FAILED"
        elif experiment.cancel_requested or RunStatus.CANCELLING in states:
            state = "CANCELLING"
        elif states == {RunStatus.QUEUED}:
            state = "QUEUED"
        else:
            state = "RUNNING"
        return ProductExperimentRead(
            id=experiment.id,
            state=state,
            cancel_requested=experiment.cancel_requested,
            baseline=baseline,
            candidate=candidate,
        )

    async def cancel(self, *, principal: Principal, experiment_id: UUID) -> ProductExperimentRead:
        if await self._repository.cancel(principal=principal, experiment_id=experiment_id) is None:
            raise RunNotFoundError
        return await self.get(principal=principal, experiment_id=experiment_id)
