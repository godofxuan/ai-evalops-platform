"""Run an exact-case paired experiment and preserve its claim boundary."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.core.strict_json import decode_evidence_json
from app.datasets.validation import DEFAULT_JSONL_VALIDATION_LIMITS
from app.domain.evaluation import EvaluationCase, ExecutionContext, TargetResult
from app.external_harness.formal_quality import (
    FormalArmResult,
    FormalQualityPolicy,
)
from app.external_harness.harness_envelope import canonical_sha256
from app.jobs.retry_policy import classify_failure
from app.product_experiments.agent_projection import project_agent_trace
from app.product_experiments.diagnostics import (
    CategoryDiagnostic,
    MetricDiagnostic,
)
from app.product_experiments.evaluators import (
    CaseEvaluator,
    citation_evidence_scores,
)
from app.product_experiments.measurements import ProductArmResult, ProductCaseMeasurement
from app.product_experiments.observation_contract import (
    MAX_PRODUCT_ANSWER_CHARS,
    InvalidCoarseTerminalError,
    validate_terminal_pair,
)
from app.product_experiments.spec import (
    AgentComparisonPolicy,
    ExperimentArm,
    FixtureProviderSpec,
    HTTPProviderSpec,
    InputLimitError,
    LoadedExperimentSpec,
    load_experiment_spec,
    read_bounded_config,
)
from app.targets.base import TargetExecutionError, TargetInvalidResponseError
from app.targets.http_rag import HostResolver, HTTPRAGTarget, project_request_input


class DatasetIntegrityError(ValueError):
    """The dataset bytes do not match the preregistered identity."""


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    status: Literal["success", "error"] = "success"


class ExpectedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ExperimentCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20_000)
    reference_answer: str = Field(max_length=100_000)
    expected_citation_ids: tuple[str, ...] = ()
    expected_tool_calls: tuple[ExpectedToolCall, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    max_tool_calls: int | None = Field(default=None, ge=0, le=100)
    expected_terminal_state: Literal[
        "completed",
        "failed",
        "blocked",
        "partial",
        "refusal",
        "permission_denied",
        "budget_exhausted",
        "tool_error",
        "agent_error",
    ] = "completed"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str = Field(max_length=MAX_PRODUCT_ANSWER_CHARS)
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    trace_id: str | None = None
    tool_error: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)
    terminal_state: Literal["completed", "failed", "blocked"] | None = None
    budget_exhausted: bool = False
    missing_fields: tuple[str, ...] = ()
    source_terminal_state: str | None = None
    artifact_sha256: str | None = None

    @model_validator(mode="after")
    def terminal_contract(self) -> ProviderResult:
        validate_terminal_pair(self.terminal_state, self.source_terminal_state)
        return self

    @classmethod
    def from_target(cls, values: Mapping[str, Any]) -> ProviderResult:
        answer = values.get("answer")
        if isinstance(answer, str) and len(answer) > MAX_PRODUCT_ANSWER_CHARS:
            raise TargetInvalidResponseError("target_answer_too_long")
        try:
            validate_terminal_pair(
                values.get("terminal_state"), values.get("source_terminal_state")
            )
        except InvalidCoarseTerminalError:
            raise TargetInvalidResponseError("target_agent_observation_invalid") from None
        except ValueError:
            raise TargetInvalidResponseError("target_agent_terminal_invalid") from None
        try:
            return cls.model_validate(dict(values))
        except ValidationError:
            raise TargetInvalidResponseError("target_agent_observation_invalid") from None


def product_observation_bytes(result: ProviderResult) -> int:
    """Versioned normalized observation UTF-8 bytes, not raw HTTP or database storage size."""
    return len(result.model_dump_json().encode("utf-8"))


class Provider(Protocol):
    async def execute(self, case: ExperimentCase) -> ProviderResult:
        """Execute one frozen case without changing evaluation semantics."""


class CaseComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str
    category: str
    baseline_answer: str
    candidate_answer: str
    baseline_task_success: float
    candidate_task_success: float
    task_success_delta: float
    baseline_citation_correctness: float | None
    candidate_citation_correctness: float | None
    baseline_citation_recall: float | None = None
    candidate_citation_recall: float | None = None
    baseline_citation_precision: float | None = None
    candidate_citation_precision: float | None = None
    baseline_tool_error_rate: float
    candidate_tool_error_rate: float
    baseline_latency_ms: float
    candidate_latency_ms: float
    latency_delta_ms: float
    baseline_cost_usd: float
    candidate_cost_usd: float
    cost_delta_usd: float
    baseline_trace_id: str | None
    candidate_trace_id: str | None
    baseline_tool_calls: list[dict[str, JsonValue]] = Field(default_factory=list)
    candidate_tool_calls: list[dict[str, JsonValue]] = Field(default_factory=list)
    baseline_agent_metrics: dict[str, float] = Field(default_factory=dict)
    candidate_agent_metrics: dict[str, float] = Field(default_factory=dict)


class CaseExecutionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    arm: Literal["baseline", "candidate"]
    case_id: str
    error_code: str
    retryable: bool
    upstream_status_code: int | None = None


class ProductExperimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["evalops.experiment-result/1.0", "evalops.experiment-result/2.0"] = (
        "evalops.experiment-result/2.0"
    )
    experiment_id: str
    execution_id: UUID | None = None
    input_snapshot: dict[str, Any] | None = None
    execution_schedule: list[dict[str, Any]] = Field(default_factory=list)
    execution_events: list[dict[str, Any]] = Field(default_factory=list)
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
    task_type: Literal["QA", "AGENT_TOOL_USE"] = "QA"
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evalops_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    case_count: int = Field(ge=0)
    source_identities: dict[str, dict[str, str]]
    arms: dict[str, FormalArmResult | ProductArmResult]
    automated_assessment: dict[str, Any]
    agent_tool_use_assessment: dict[str, Any] | None = None
    case_comparisons: list[CaseComparison]
    human_review_status: Literal["PENDING"] = "PENDING"
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False
    input_requirements: list[dict[str, str]] = Field(default_factory=list)
    execution_errors: list[CaseExecutionFailure] = Field(default_factory=list)
    observations: dict[str, dict[str, ProviderResult]] = Field(default_factory=dict)
    metric_diagnostics: dict[str, MetricDiagnostic] = Field(default_factory=dict)
    category_diagnostics: dict[str, CategoryDiagnostic] = Field(default_factory=dict)


class _FixtureProvider:
    def __init__(self, profile: str, *, task_type: str = "QA") -> None:
        self._profile = profile
        self._task_type = task_type

    async def execute(self, case: ExperimentCase) -> ProviderResult:
        profiles = case.metadata.get("fixture_profiles")
        if not isinstance(profiles, dict):
            raise ValueError(f"case {case.case_id} has no fixture_profiles")
        raw = profiles.get(self._profile)
        if not isinstance(raw, dict):
            raise ValueError(f"case {case.case_id} has no fixture profile {self._profile}")
        result = ProviderResult.from_target(raw)
        if self._task_type == "AGENT_TOOL_USE" and result.terminal_state is None:
            result = result.model_copy(
                update={
                    "missing_fields": tuple(sorted(set(result.missing_fields) | {"terminal_state"}))
                }
            )
        return result


class _HTTPProvider:
    def __init__(
        self,
        config: HTTPProviderSpec,
        *,
        experiment_id: str,
        arm: str,
        task_type: Literal["QA", "AGENT_TOOL_USE"] = "QA",
        execution_id: UUID | None = None,
        http_client: httpx.AsyncClient | None = None,
        host_resolver: HostResolver | None = None,
    ) -> None:
        hostname = urlsplit(config.base_url).hostname
        target_config = config.model_dump(exclude={"type"})
        target_config["allowed_hosts"] = ["" if hostname is None else hostname]
        self._target = HTTPRAGTarget(target_config, client=http_client, resolver=host_resolver)
        self._experiment_id = experiment_id
        self._execution_id = execution_id or uuid4()
        self._arm = arm
        self._task_type = task_type

    async def execute(self, case: ExperimentCase) -> ProviderResult:
        identity = f"{self._execution_id}:{self._experiment_id}:{self._arm}:{case.case_id}"
        context = ExecutionContext(
            run_id=uuid5(NAMESPACE_URL, f"run:{self._execution_id}:{self._arm}"),
            job_id=uuid5(NAMESPACE_URL, f"job:{identity}"),
            attempt_id=uuid5(NAMESPACE_URL, f"attempt:{identity}"),
            attempt_number=1,
            worker_id="product-experiment-runner",
            cancellation=asyncio.Event(),
        )
        target_result = await self._target.execute_case(
            EvaluationCase(
                case_id=case.case_id,
                question=case.prompt,
                expected_answer=case.reference_answer,
                metadata=cast(dict[str, Any], case.metadata),
            ),
            context,
        )
        return normalize_product_observation(case, target_result, task_type=self._task_type)


def normalize_product_observation(
    case: ExperimentCase,
    target_result: TargetResult,
    *,
    task_type: Literal["QA", "AGENT_TOOL_USE"],
) -> ProviderResult:
    """Use one response normalization contract in local and durable evaluation."""
    usage = target_result.token_usage
    trace = (
        project_agent_trace(target_result.trace, case_id=case.case_id, answer=target_result.answer)
        if task_type == "AGENT_TOOL_USE"
        else target_result.trace
    )
    trace_id = trace.get("trace_id")
    return ProviderResult.from_target(
        {
            "answer": target_result.answer or "",
            "citations": list(target_result.citations),
            "latency_ms": float(target_result.latency_ms),
            "cost_usd": _reported_cost(trace, usage),
            "trace_id": trace_id if isinstance(trace_id, str) else None,
            "missing_fields": tuple(
                name
                for name in ("tool_error", "tool_calls", "terminal_state", "budget_exhausted")
                if name not in trace or trace[name] is None
            )
            + tuple(trace.get("projection_missing_fields", ())),
            **{
                name: trace[name]
                for name in (
                    "tool_error",
                    "tool_calls",
                    "terminal_state",
                    "budget_exhausted",
                    "source_terminal_state",
                    "artifact_sha256",
                )
                if name in trace
            },
        }
    )


def _reported_cost(trace: Mapping[str, Any], usage: object) -> float | None:
    value = trace.get("cost_usd")
    # Token counts alone do not establish a cost without a pinned applicable price contract.
    del usage
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise TargetInvalidResponseError("target_cost_invalid")
    return float(value)


def _load_dataset(path: str, expected_sha256: str) -> list[ExperimentCase]:
    with open(path, "rb") as stream:
        payload = stream.read(DEFAULT_JSONL_VALIDATION_LIMITS.max_file_bytes + 1)
    return parse_product_dataset(payload, expected_sha256=expected_sha256)


def parse_product_dataset(payload: bytes, *, expected_sha256: str) -> list[ExperimentCase]:
    """Validate the exact source bytes shared by local execution and durable mapping."""
    if len(payload) > DEFAULT_JSONL_VALIDATION_LIMITS.max_file_bytes:
        raise DatasetIntegrityError("dataset size limit exceeded")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise DatasetIntegrityError(
            f"dataset SHA-256 mismatch: expected {expected_sha256}, computed {actual}"
        )
    decode_evidence_json(payload)
    cases = TypeAdapter(list[ExperimentCase]).validate_json(payload)
    if not 2 <= len(cases) <= DEFAULT_JSONL_VALIDATION_LIMITS.max_cases:
        raise DatasetIntegrityError("dataset case count must be between 2 and 10000")
    case_ids = [case.case_id for case in cases]
    if any(len(case.model_dump_json().encode("utf-8")) > 1024 * 1024 for case in cases):
        raise DatasetIntegrityError("dataset case byte limit exceeded")
    if len(case_ids) != len(set(case_ids)):
        raise DatasetIntegrityError("dataset contains duplicate case_id")
    return cases


def _input_requirements(arms: tuple[ExperimentArm, ExperimentArm]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for arm in arms:
        provider = arm.provider
        if (
            isinstance(provider, HTTPProviderSpec)
            and provider.auth_env_var is not None
            and not os.environ.get(provider.auth_env_var)
        ):
            missing.append(
                {
                    "arm": arm.label,
                    "code": "MISSING_CREDENTIAL_ENV",
                    "environment_variable": provider.auth_env_var,
                }
            )
    return missing


def _prepare_experiment(
    spec_path: Path,
) -> tuple[
    LoadedExperimentSpec,
    list[ExperimentCase],
    FormalQualityPolicy,
    list[dict[str, str]],
    dict[str, list[str]],
    dict[str, Any],
]:
    loaded = load_experiment_spec(spec_path)
    spec = loaded.spec
    cases = _load_dataset(str(loaded.dataset_path), spec.dataset.sha256)
    if spec.task_type == "AGENT_TOOL_USE":
        invalid = [
            case.case_id
            for case in cases
            if (
                "allowed_tools" not in case.model_fields_set
                or case.max_tool_calls is None
                or any(call.name not in case.allowed_tools for call in case.expected_tool_calls)
                or len(case.expected_tool_calls) > case.max_tool_calls
            )
        ]
        if invalid:
            raise DatasetIntegrityError(
                "agent cases require explicit, consistent allowed_tools and max_tool_calls: "
                + ", ".join(invalid[:5])
            )
    policy_payload = read_bounded_config(loaded.policy_path)
    decode_evidence_json(policy_payload)
    policy = FormalQualityPolicy.model_validate_json(policy_payload)
    if policy.bootstrap_resamples > 10_000 or len(cases) * policy.bootstrap_resamples > 2_000_000:
        raise InputLimitError("bootstrap work limit exceeded")
    requirements = _input_requirements(spec.arms)
    if spec.task_type == "QA":
        requirements.extend(
            {"arm": "experiment", "case_id": case.case_id, "code": "MISSING_CITATION_LABELS"}
            for case in cases
            if not case.expected_citation_ids
        )
    if spec.scope == "FORMAL":
        # The v1 experiment input has no independently verified provenance contract.
        # A label or HTTP transport cannot substitute for that missing evidence.
        for arm in spec.arms:
            requirements.append(
                {
                    "arm": arm.label,
                    "code": (
                        "FORMAL_FIXTURE_NOT_ELIGIBLE"
                        if isinstance(arm.provider, FixtureProviderSpec)
                        else "FORMAL_PROVENANCE_CONTRACT_REQUIRED"
                    ),
                }
            )
    request_fields: dict[str, list[str]] = {}
    for arm in spec.arms:
        if isinstance(arm.provider, HTTPProviderSpec):
            _build_provider(arm, experiment_id=spec.experiment_id, task_type=spec.task_type)
            for case in cases:
                payload = project_request_input(
                    EvaluationCase(
                        case.case_id,
                        case.prompt,
                        case.reference_answer,
                        cast(dict[str, Any], case.metadata),
                    ),
                    question_field=arm.provider.request_question_field,
                    include_metadata=arm.provider.include_metadata,
                )
                request_fields[arm.label] = sorted(payload)
    configuration = spec.model_dump(mode="json", exclude={"experiment_id", "policy_path"})
    configuration["dataset"] = {"sha256": spec.dataset.sha256}
    frozen_policy = policy.model_dump(mode="json")
    snapshot = {
        "schema_version": "evalops.experiment-input-snapshot/1.0",
        "spec_sha256": loaded.spec_sha256,
        "dataset_sha256": spec.dataset.sha256,
        "policy_sha256": hashlib.sha256(policy_payload).hexdigest(),
        "configuration": configuration,
        "policy": frozen_policy,
        "content_sha256": canonical_sha256(
            {"configuration": configuration, "policy": frozen_policy}
        ),
    }
    return loaded, cases, policy, requirements, request_fields, snapshot


def preflight_experiment(spec_path: Path) -> dict[str, Any]:
    """Validate the same local inputs as execution without calling targets."""
    loaded, cases, _, requirements, request_fields, snapshot = _prepare_experiment(spec_path)
    spec = loaded.spec
    return {
        "schema_version": "evalops.experiment-preflight/1.0",
        "status": "INPUT_REQUIRED" if requirements else "READY",
        "execution_status": "NOT_RUN",
        "case_count": len(cases),
        "planned_case_executions": len(cases) * 2,
        "planned_http_calls": len(cases)
        * sum(isinstance(arm.provider, HTTPProviderSpec) for arm in spec.arms),
        "request_fields": request_fields,
        "input_content_sha256": snapshot["content_sha256"],
        "input_requirements": requirements,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }


async def run_experiment(
    spec_path: object,
    *,
    evalops_sha: str,
    http_client: httpx.AsyncClient | None = None,
    host_resolver: HostResolver | None = None,
) -> ProductExperimentResult:
    loaded, cases, policy, requirements, _, snapshot = _prepare_experiment(
        Path(cast(str | Path, spec_path))
    )
    spec = loaded.spec
    execution_id = uuid4()
    source_identities: dict[str, dict[str, str]] = {
        arm.label: {
            "repository": arm.source_repository,
            "sha": arm.source_sha,
            "provider_type": arm.provider.type,
        }
        for arm in spec.arms
    }
    if requirements:
        return ProductExperimentResult(
            experiment_id=spec.experiment_id,
            status="INPUT_REQUIRED",
            input_snapshot=snapshot,
            execution_id=execution_id,
            scope=spec.scope,
            task_type=spec.task_type,
            dataset_sha256=spec.dataset.sha256,
            evalops_sha=evalops_sha,
            case_count=len(cases),
            source_identities=source_identities,
            arms={},
            automated_assessment={"status": "NOT_RUN"},
            case_comparisons=[],
            input_requirements=requirements,
        )

    providers = {
        arm.label: _build_provider(
            arm,
            experiment_id=spec.experiment_id,
            execution_id=execution_id,
            http_client=http_client,
            host_resolver=host_resolver,
            task_type=spec.task_type,
        )
        for arm in spec.arms
    }
    semaphore = asyncio.Semaphore(spec.max_concurrency)
    execution_errors: list[CaseExecutionFailure] = []
    observed_results: dict[str, dict[str, ProviderResult]] = {arm.label: {} for arm in spec.arms}
    retained_observation_bytes = 0
    observation_budget_exhausted = False

    async def measure(arm: ExperimentArm, case: ExperimentCase) -> None:
        nonlocal retained_observation_bytes, observation_budget_exhausted
        async with semaphore:
            try:
                if observation_budget_exhausted:
                    raise TargetExecutionError(
                        "experiment_observation_budget_exceeded",
                        "experiment observation budget exhausted",
                        retryable=False,
                    )
                result = await providers[arm.label].execute(case)
                byte_size = product_observation_bytes(result)
                if retained_observation_bytes + byte_size > spec.max_observation_bytes:
                    observation_budget_exhausted = True
                    raise TargetExecutionError(
                        "experiment_observation_budget_exceeded",
                        "experiment observation budget exhausted",
                        retryable=False,
                    )
                retained_observation_bytes += byte_size
            except Exception as error:
                failure = classify_failure(error)
                execution_errors.append(
                    CaseExecutionFailure(
                        arm=arm.label,
                        case_id=case.case_id,
                        error_code=failure.error_code,
                        retryable=failure.retryable,
                        upstream_status_code=failure.upstream_status_code,
                    )
                )
                return None
            observed_results[arm.label][case.case_id] = result

    rng = random.Random(spec.order_seed)
    first_arms: list[int] = []
    for _ in range(0, len(cases), 2):
        first = rng.randrange(2)
        first_arms.extend((first, 1 - first))
    schedule = [
        {
            "case_id": case.case_id,
            "arms": [spec.arms[first_arms[index]].label, spec.arms[1 - first_arms[index]].label],
        }
        for index, case in enumerate(cases)
    ]
    events: list[dict[str, Any]] = []
    pending = iter(enumerate(cases))

    async def consume_pairs() -> None:
        for index, case in pending:
            for arm_index in (first_arms[index], 1 - first_arms[index]):
                arm = spec.arms[arm_index]
                event = {
                    "case_id": case.case_id,
                    "arm": arm.label,
                    "started_at_utc": datetime.now(UTC).isoformat(),
                }
                events.append(event)
                try:
                    await measure(arm, case)
                finally:
                    event["finished_at_utc"] = datetime.now(UTC).isoformat()
                    event["observation_status"] = (
                        "OBSERVED"
                        if case.case_id in observed_results[arm.label]
                        else "NO_VALID_OBSERVATION"
                    )

    deadline = asyncio.get_running_loop().time() + spec.execution_timeout_seconds
    try:
        async with asyncio.timeout_at(deadline):
            await asyncio.gather(
                *(consume_pairs() for _ in range(min(spec.max_concurrency, len(cases))))
            )
    except TimeoutError:
        failed = {(error.arm, error.case_id) for error in execution_errors}
        for pending_arm in spec.arms:
            for case in cases:
                if (
                    case.case_id not in observed_results[pending_arm.label]
                    and (pending_arm.label, case.case_id) not in failed
                ):
                    execution_errors.append(
                        CaseExecutionFailure(
                            arm=pending_arm.label,
                            case_id=case.case_id,
                            error_code="experiment_deadline_exceeded",
                            retryable=False,
                        )
                    )
    # Local execution and durable export share this pure, no-network aggregation path.
    from app.product_experiments.aggregation import (
        ProductAggregationContext,
        aggregate_product_observations,
    )

    return aggregate_product_observations(
        context=ProductAggregationContext(
            experiment_id=spec.experiment_id,
            execution_id=execution_id,
            scope=spec.scope,
            task_type=spec.task_type,
            dataset_sha256=spec.dataset.sha256,
            evalops_sha=evalops_sha,
            source_identities=source_identities,
            input_snapshot=snapshot,
            policy=policy,
            agent_comparison_policy=spec.agent_comparison_policy,
            citation_precision_min=spec.citation_precision_min,
            evaluator_names=spec.evaluators,
        ),
        cases=cases,
        observations=observed_results,
        execution_errors=execution_errors,
        execution_schedule=schedule,
        execution_events=events,
    )


def _build_provider(
    arm: ExperimentArm,
    *,
    experiment_id: str,
    task_type: Literal["QA", "AGENT_TOOL_USE"] = "QA",
    execution_id: UUID | None = None,
    http_client: httpx.AsyncClient | None = None,
    host_resolver: HostResolver | None = None,
) -> Provider:
    if isinstance(arm.provider, FixtureProviderSpec):
        return _FixtureProvider(arm.provider.profile, task_type=task_type)
    return _HTTPProvider(
        arm.provider,
        experiment_id=experiment_id,
        arm=arm.label,
        task_type=task_type,
        execution_id=execution_id,
        http_client=http_client,
        host_resolver=host_resolver,
    )


def _measurement(
    case: ExperimentCase,
    result: ProviderResult,
    *,
    scores: dict[str, float],
    task_type: Literal["QA", "AGENT_TOOL_USE"],
) -> ProductCaseMeasurement:
    if result.cost_usd is None:
        raise ValueError("a missing cost cannot enter the legacy numeric statistics adapter")
    task_score = (
        scores["reference_answer"] if task_type == "QA" else scores["agent_task_completion"]
    )
    return ProductCaseMeasurement(
        case_id=case.case_id,
        category=case.category,
        prompt=case.prompt,
        task_success=task_score,
        citation_correctness=scores.get("citation_correctness"),
        citation_recall=scores.get("citation_recall"),
        citation_precision=scores.get("citation_precision"),
        tool_error_rate=scores["tool_error_rate"],
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        answer=result.answer,
        citations=result.citations,
        trace_id=result.trace_id,
    )


def score_product_case(
    case: ExperimentCase,
    result: ProviderResult,
    *,
    evaluators: tuple[CaseEvaluator, ...],
) -> dict[str, float]:
    scores = {evaluator.name: evaluator.evaluate(case, result) for evaluator in evaluators}
    if "citation_correctness" in scores:
        recall, precision = citation_evidence_scores(case, result)
        if recall is not None and precision is not None:
            scores.update(
                citation_correctness=recall, citation_recall=recall, citation_precision=precision
            )
    return scores


def _agent_assessment(
    results: dict[str, dict[str, dict[str, float]]],
    *,
    policy: AgentComparisonPolicy,
) -> dict[str, Any]:
    positive = {"agent_task_completion", "tool_selection_accuracy", "tool_argument_validity"}
    metrics: dict[str, dict[str, float | bool | str]] = {}
    for name, threshold in policy.thresholds.items():
        baseline_values = [scores[name] for scores in results["baseline"].values()]
        candidate_values = [scores[name] for scores in results["candidate"].values()]
        baseline_mean = sum(baseline_values) / len(baseline_values)
        candidate_mean = sum(candidate_values) / len(candidate_values)
        qualified = candidate_mean >= threshold if name in positive else candidate_mean <= threshold
        regression = (
            baseline_mean - candidate_mean if name in positive else candidate_mean - baseline_mean
        )
        non_regression = regression <= policy.regression_tolerance
        passed = (policy.mode == "non_regression" or qualified) and (
            policy.mode == "qualification" or non_regression
        )
        operator = ">=" if name in positive else "<="
        metrics[name] = {
            "baseline_mean": baseline_mean,
            "candidate_mean": candidate_mean,
            "paired_delta": candidate_mean - baseline_mean,
            "passed": passed,
            "qualification_passed": qualified,
            "non_regression_passed": non_regression,
            "rule": (
                f"mode={policy.mode}; candidate_mean {operator} {threshold}; "
                f"regression <= {policy.regression_tolerance}"
            ),
        }
    return {
        "status": "PASS" if all(bool(item["passed"]) for item in metrics.values()) else "FAIL",
        "qualification_status": "PASS"
        if all(item["qualification_passed"] for item in metrics.values())
        else "FAIL",
        "non_regression_status": "PASS"
        if all(item["non_regression_passed"] for item in metrics.values())
        else "FAIL",
        "mode": policy.mode,
        "method": "exact-common-case descriptive means; not a formal statistical quality claim",
        "metrics": metrics,
    }


def _comparisons(
    baseline: ProductArmResult,
    candidate: ProductArmResult,
    *,
    provider_results: dict[str, dict[str, ProviderResult]],
    score_results: dict[str, dict[str, dict[str, float]]],
    task_type: Literal["QA", "AGENT_TOOL_USE"],
) -> list[CaseComparison]:
    left = {case.case_id: case for case in baseline.cases}
    right = {case.case_id: case for case in candidate.cases}
    return [
        CaseComparison(
            case_id=case_id,
            category=left[case_id].category,
            baseline_answer=left[case_id].answer,
            candidate_answer=right[case_id].answer,
            baseline_task_success=left[case_id].task_success,
            candidate_task_success=right[case_id].task_success,
            task_success_delta=right[case_id].task_success - left[case_id].task_success,
            baseline_citation_correctness=left[case_id].citation_correctness,
            candidate_citation_correctness=right[case_id].citation_correctness,
            baseline_citation_recall=left[case_id].citation_recall,
            candidate_citation_recall=right[case_id].citation_recall,
            baseline_citation_precision=left[case_id].citation_precision,
            candidate_citation_precision=right[case_id].citation_precision,
            baseline_tool_error_rate=left[case_id].tool_error_rate,
            candidate_tool_error_rate=right[case_id].tool_error_rate,
            baseline_latency_ms=left[case_id].latency_ms,
            candidate_latency_ms=right[case_id].latency_ms,
            latency_delta_ms=right[case_id].latency_ms - left[case_id].latency_ms,
            baseline_cost_usd=left[case_id].cost_usd,
            candidate_cost_usd=right[case_id].cost_usd,
            cost_delta_usd=right[case_id].cost_usd - left[case_id].cost_usd,
            baseline_trace_id=left[case_id].trace_id,
            candidate_trace_id=right[case_id].trace_id,
            baseline_tool_calls=[
                call.model_dump(mode="json")
                for call in provider_results["baseline"][case_id].tool_calls
            ],
            candidate_tool_calls=[
                call.model_dump(mode="json")
                for call in provider_results["candidate"][case_id].tool_calls
            ],
            baseline_agent_metrics=(
                score_results["baseline"][case_id] if task_type == "AGENT_TOOL_USE" else {}
            ),
            candidate_agent_metrics=(
                score_results["candidate"][case_id] if task_type == "AGENT_TOOL_USE" else {}
            ),
        )
        for case_id in sorted(left)
    ]


__all__ = [
    "DatasetIntegrityError",
    "ProductExperimentResult",
    "run_experiment",
    "preflight_experiment",
]
