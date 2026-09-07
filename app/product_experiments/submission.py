"""Prepare a frozen durable pair outside its atomic database write transaction."""

import json
import re
from dataclasses import replace
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.principals import Principal
from app.core.clock import Clock, SystemClock
from app.domain.evaluation import EvaluationCase
from app.external_harness.formal_quality import FormalQualityPolicy
from app.product_experiments.dataset_mapping import map_product_dataset
from app.product_experiments.persistence import NewProductExperiment
from app.product_experiments.spec import AgentComparisonPolicy, InputLimitError
from app.runs.idempotency import canonical_request_hash
from app.runs.repository import NewRun
from app.runs.schemas import ComponentSpec, RunCreate
from app.runs.service import RunInputIntegrityError, SQLAlchemyRunService
from app.targets.http_rag import project_request_input


class RegisteredExperimentArm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    target_version: str = Field(min_length=1, max_length=128)
    source_repository: str = Field(min_length=1, max_length=500)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")

    @field_validator("source_repository")
    @classmethod
    def repository_has_no_credentials(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "demo"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("source repository must not contain credentials or query parameters")
        return value


class DurableExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schema_version: Literal["evalops.durable-experiment-request/1.0"]
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    scope: Literal["DEMO"] = "DEMO"
    task_type: Literal["QA", "AGENT_TOOL_USE"]
    dataset_version_id: UUID
    source_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline: RegisteredExperimentArm
    candidate: RegisteredExperimentArm
    policy: FormalQualityPolicy
    agent_comparison_policy: AgentComparisonPolicy = Field(default_factory=AgentComparisonPolicy)
    citation_precision_min: float = Field(default=0.95, ge=0, le=1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_total_attempts: int = Field(default=20_000, ge=1, le=200_000)
    execution_timeout_seconds: float = Field(default=3600.0, gt=0, le=86_400)

    @model_validator(mode="after")
    def bounded_policy(self) -> "DurableExperimentRequest":
        if (
            self.policy.bootstrap_resamples > 10_000
            or len(self.policy.required_categories) > 100
            or any(len(value) > 100 for value in self.policy.required_categories)
        ):
            raise ValueError("durable policy exceeds computation or category limits")
        return self


async def prepare_durable_experiment(
    *,
    principal: Principal,
    idempotency_key: str,
    request: DurableExperimentRequest,
    dataset_payload: bytes,
    run_service: SQLAlchemyRunService,
    evalops_sha: str,
    clock: Clock | None = None,
) -> NewProductExperiment:
    """No target calls and no Run/Job writes. Caller owns replay and atomic persistence."""
    if not re.fullmatch(r"[0-9a-f]{40}", evalops_sha):
        raise ValueError("server execution code identity is required")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
        raise ValueError("invalid experiment idempotency key")
    request = DurableExperimentRequest.model_validate_json(request.model_dump_json())
    clock = clock or SystemClock()
    started = clock.now()
    if started.tzinfo is None or started.utcoffset() is None:
        raise ValueError("execution clock must be timezone-aware")
    deadline = started + timedelta(seconds=request.execution_timeout_seconds)
    mapped = map_product_dataset(dataset_payload, expected_sha256=request.source_dataset_sha256)
    count = mapped.dataset.case_count
    if count * request.policy.bootstrap_resamples > 2_000_000:
        raise InputLimitError("paired bootstrap computation limit exceeded")
    if 2 * count * request.max_attempts > request.max_total_attempts:
        raise InputLimitError("attempt budget cannot cover both arms and retries")
    prepared: list[NewRun] = []
    for label, arm in (("baseline", request.baseline), ("candidate", request.candidate)):
        pending = await run_service.prepare_run(
            principal=principal,
            idempotency_key=f"{idempotency_key}:{label}",
            request=RunCreate(
                dataset_version_id=request.dataset_version_id,
                target=ComponentSpec(
                    type="http_rag", config={"target_id": arm.target_id}, version=arm.target_version
                ),
                evaluator=ComponentSpec(
                    type="product_qa_v2" if request.task_type == "QA" else "product_agent_v2",
                    version="product-v2",
                    config={"max_attempts": request.max_attempts},
                ),
                source_commit=arm.source_sha,
            ),
        )
        if pending.dataset_hash != mapped.dataset.sha256 or len(pending.cases) != count:
            raise RunInputIntegrityError("product mapping differs from authorized dataset version")
        for case in pending.cases:
            project_request_input(
                EvaluationCase.from_payload(case),
                question_field=pending.target_config.get("request_question_field", "question"),
                include_metadata=pending.target_config.get("include_metadata", False),
            )
        prepared.append(replace(pending, execution_deadline_at=deadline))
    if clock.now() >= deadline:
        raise InputLimitError("experiment deadline exhausted during preparation")
    frozen_request = request.model_dump(mode="json")
    # This is a different schema from local snapshots, not a fake local execution.
    snapshot = {
        "schema_version": "evalops.durable-experiment-input/1.0",
        "request": frozen_request,
        "source_dataset_sha256": mapped.source_sha256,
        "normalized_dataset_sha256": mapped.dataset.sha256,
        "mapping_version": mapped.mapping_version,
        "evalops_sha": evalops_sha,
        "source_sha_attestation": "CLIENT_DECLARED",
        "execution_deadline_at": deadline.isoformat(),
        "components": {
            label: {
                "target_config_sha256": arm.target_config_hash,
                "evaluator_config_sha256": arm.evaluator_config_hash,
                "target_version": arm.target_version,
                "evaluator_version": arm.evaluator_version,
            }
            for label, arm in zip(("baseline", "candidate"), prepared, strict=True)
        },
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    if len(json.dumps(snapshot, allow_nan=False).encode("utf-8")) > 1024 * 1024:
        raise InputLimitError("durable input snapshot exceeds size limit")
    pending_experiment = NewProductExperiment(
        tenant_id=principal.tenant_id,
        created_by=principal.api_key_id,
        idempotency_key=idempotency_key,
        request_hash=canonical_request_hash(frozen_request),
        snapshot=snapshot,
        baseline=prepared[0],
        candidate=prepared[1],
        max_total_attempts=request.max_total_attempts,
    )
    return replace(pending_experiment, snapshot=pending_experiment.snapshot_with_attempt_budget())
