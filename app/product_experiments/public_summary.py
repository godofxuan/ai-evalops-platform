"""Allowlisted public projection; no free text or per-case payload is published."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.product_experiments.runner import ProductExperimentResult


class PublicExperimentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["evalops.public-experiment-summary/1.0"] = (
        "evalops.public-experiment-summary/1.0"
    )
    experiment_id: str = Field(pattern=r"^public-[0-9a-f]{64}$")
    execution_id: UUID | None
    status: Literal[
        "DEMO_PASS",
        "DEMO_FAIL",
        "AUTOMATED_PASS_HUMAN_REVIEW_PENDING",
        "AUTOMATED_FAIL",
        "INSUFFICIENT_EVIDENCE",
        "INPUT_REQUIRED",
        "EXECUTION_FAILED",
    ]
    scope: Literal["DEMO", "FORMAL"]
    task_type: Literal["QA", "AGENT_TOOL_USE"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evalops_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    case_count: int = Field(ge=0)
    observed_case_arm_count: int = Field(ge=0)
    execution_error_count: int = Field(ge=0)
    private_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    private_payload_status: Literal["NOT_EXPORTED"] = "NOT_EXPORTED"
    verification_scope: Literal["PUBLIC_PROJECTION_ONLY"] = "PUBLIC_PROJECTION_ONLY"
    human_review_status: Literal["PENDING"] = "PENDING"
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False


def project_public_summary(
    result: ProductExperimentResult, *, private_result_sha256: str
) -> PublicExperimentSummary:
    return PublicExperimentSummary(
        experiment_id="public-" + hashlib.sha256(result.experiment_id.encode()).hexdigest(),
        execution_id=result.execution_id,
        status=result.status,
        scope=result.scope,
        task_type=result.task_type,
        dataset_sha256=result.dataset_sha256,
        evalops_sha=result.evalops_sha,
        case_count=result.case_count,
        observed_case_arm_count=sum(len(cases) for cases in result.observations.values()),
        execution_error_count=len(result.execution_errors),
        private_result_sha256=private_result_sha256,
    )
