"""Run an exact-case paired experiment and preserve its claim boundary."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Mapping
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.evaluation import EvaluationCase, ExecutionContext
from app.external_harness.formal_quality import (
    FormalArmResult,
    FormalCaseMeasurement,
    FormalQualityPolicy,
    assess_formal_quality,
)
from app.product_experiments.spec import (
    ExperimentArm,
    FixtureProviderSpec,
    HTTPProviderSpec,
    load_experiment_spec,
)
from app.targets.http_rag import HTTPRAGTarget


class DatasetIntegrityError(ValueError):
    """The dataset bytes do not match the preregistered identity."""


class ExperimentCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20_000)
    reference_answer: str = Field(max_length=100_000)
    expected_citation_ids: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    trace_id: str | None = None
    tool_error: bool = False


class Provider(Protocol):
    async def execute(self, case: ExperimentCase) -> ProviderResult:
        """Execute one frozen case without changing evaluation semantics."""


class CaseComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str
    category: str
    baseline_answer: str
    candidate_answer: str
    task_success_delta: float
    latency_delta_ms: float
    cost_delta_usd: float


class ProductExperimentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["evalops.experiment-result/1.0"] = "evalops.experiment-result/1.0"
    experiment_id: str
    status: Literal[
        "DEMO_PASS",
        "DEMO_FAIL",
        "AUTOMATED_PASS_HUMAN_REVIEW_PENDING",
        "AUTOMATED_FAIL",
        "INSUFFICIENT_EVIDENCE",
        "INPUT_REQUIRED",
    ]
    scope: Literal["DEMO", "FORMAL"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evalops_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    case_count: int = Field(ge=0)
    source_identities: dict[str, dict[str, str]]
    arms: dict[str, FormalArmResult]
    automated_assessment: dict[str, Any]
    case_comparisons: list[CaseComparison]
    human_review_status: Literal["PENDING"] = "PENDING"
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False
    input_requirements: list[dict[str, str]] = Field(default_factory=list)


class _FixtureProvider:
    def __init__(self, profile: str) -> None:
        self._profile = profile

    async def execute(self, case: ExperimentCase) -> ProviderResult:
        profiles = case.metadata.get("fixture_profiles")
        if not isinstance(profiles, dict):
            raise ValueError(f"case {case.case_id} has no fixture_profiles")
        raw = profiles.get(self._profile)
        if not isinstance(raw, dict):
            raise ValueError(f"case {case.case_id} has no fixture profile {self._profile}")
        return ProviderResult.model_validate(raw)


class _HTTPProvider:
    def __init__(self, config: HTTPProviderSpec, *, experiment_id: str, arm: str) -> None:
        hostname = urlsplit(config.base_url).hostname
        target_config = config.model_dump(exclude={"type"})
        target_config["allowed_hosts"] = ["" if hostname is None else hostname]
        self._target = HTTPRAGTarget(target_config)
        self._experiment_id = experiment_id
        self._arm = arm

    async def execute(self, case: ExperimentCase) -> ProviderResult:
        identity = f"{self._experiment_id}:{self._arm}:{case.case_id}"
        context = ExecutionContext(
            run_id=uuid5(NAMESPACE_URL, f"run:{self._experiment_id}:{self._arm}"),
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
        usage = target_result.token_usage
        trace_id = target_result.trace.get("trace_id")
        return ProviderResult(
            answer=target_result.answer or "",
            citations=cast(list[dict[str, JsonValue]], list(target_result.citations)),
            latency_ms=float(target_result.latency_ms),
            cost_usd=_reported_cost(target_result.trace, usage),
            trace_id=trace_id if isinstance(trace_id, str) else None,
            tool_error=False,
        )


def _reported_cost(trace: Mapping[str, Any], usage: object) -> float:
    value = trace.get("cost_usd")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    # Token counts are preserved by the core platform, but pricing is model-specific. A missing
    # price must remain zero rather than being estimated from an unpinned pricing table.
    del usage
    return 0.0


def _load_dataset(path: str, expected_sha256: str) -> list[ExperimentCase]:
    with open(path, "rb") as stream:
        payload = stream.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise DatasetIntegrityError(
            f"dataset SHA-256 mismatch: expected {expected_sha256}, computed {actual}"
        )
    cases = TypeAdapter(list[ExperimentCase]).validate_json(payload)
    case_ids = [case.case_id for case in cases]
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


async def run_experiment(spec_path: object, *, evalops_sha: str) -> ProductExperimentResult:
    from pathlib import Path

    loaded = load_experiment_spec(Path(cast(str | Path, spec_path)))
    spec = loaded.spec
    cases = _load_dataset(str(loaded.dataset_path), spec.dataset.sha256)
    policy = FormalQualityPolicy.model_validate_json(loaded.policy_path.read_text(encoding="utf-8"))
    requirements = _input_requirements(spec.arms)
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
            scope=spec.scope,
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
        )
        for arm in spec.arms
    }
    semaphore = asyncio.Semaphore(spec.max_concurrency)

    async def measure(arm: ExperimentArm, case: ExperimentCase) -> FormalCaseMeasurement:
        async with semaphore:
            started = time.perf_counter()
            try:
                result = await providers[arm.label].execute(case)
            except Exception:
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1_000)
                result = ProviderResult(
                    answer="",
                    citations=[],
                    latency_ms=elapsed_ms,
                    cost_usd=0.0,
                    tool_error=True,
                )
            return _measurement(case, result)

    measurements: dict[str, list[FormalCaseMeasurement]] = {}
    for arm in spec.arms:
        measurements[arm.label] = list(
            await asyncio.gather(*(measure(arm, case) for case in cases))
        )
    baseline_arm, candidate_arm = spec.arms
    baseline = FormalArmResult(
        schema_version="formal-agent-quality-arm/1.0",
        arm="baseline",
        source_sha=baseline_arm.source_sha,
        dataset_sha256=spec.dataset.sha256,
        cases=measurements["baseline"],
    )
    candidate = FormalArmResult(
        schema_version="formal-agent-quality-arm/1.0",
        arm="candidate",
        source_sha=candidate_arm.source_sha,
        dataset_sha256=spec.dataset.sha256,
        cases=measurements["candidate"],
    )
    assessment = assess_formal_quality(
        baseline=baseline,
        candidate=candidate,
        policy=policy,
        evalops_sha=evalops_sha,
        trace_status="PASS",
        failure_matrix_status="PASS",
        formal_ab_eligible=spec.scope == "FORMAL",
    )
    status: Literal[
        "DEMO_PASS",
        "DEMO_FAIL",
        "AUTOMATED_PASS_HUMAN_REVIEW_PENDING",
        "AUTOMATED_FAIL",
        "INSUFFICIENT_EVIDENCE",
    ]
    if spec.scope == "DEMO":
        status = "DEMO_PASS" if assessment.status == "PASS" else "DEMO_FAIL"
    elif assessment.status == "PASS":
        status = "AUTOMATED_PASS_HUMAN_REVIEW_PENDING"
    elif assessment.status == "INSUFFICIENT_EVIDENCE":
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "AUTOMATED_FAIL"
    return ProductExperimentResult(
        experiment_id=spec.experiment_id,
        status=status,
        scope=spec.scope,
        dataset_sha256=spec.dataset.sha256,
        evalops_sha=evalops_sha,
        case_count=len(cases),
        source_identities=source_identities,
        arms={"baseline": baseline, "candidate": candidate},
        automated_assessment=assessment.as_json(),
        case_comparisons=_comparisons(baseline, candidate),
    )


def _build_provider(arm: ExperimentArm, *, experiment_id: str) -> Provider:
    if isinstance(arm.provider, FixtureProviderSpec):
        return _FixtureProvider(arm.provider.profile)
    return _HTTPProvider(arm.provider, experiment_id=experiment_id, arm=arm.label)


def _measurement(case: ExperimentCase, result: ProviderResult) -> FormalCaseMeasurement:
    actual_ids = {
        str(value)
        for citation in result.citations
        for key in ("source_id", "id")
        if (value := citation.get(key)) is not None
    }
    expected_ids = set(case.expected_citation_ids)
    citation_correctness = (
        1.0 if not expected_ids else len(expected_ids & actual_ids) / len(expected_ids)
    )
    return FormalCaseMeasurement(
        case_id=case.case_id,
        category=case.category,
        prompt=case.prompt,
        task_success=float(_normalize(result.answer) == _normalize(case.reference_answer)),
        citation_correctness=citation_correctness,
        tool_error_rate=float(result.tool_error),
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        answer=result.answer,
        citations=result.citations,
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _comparisons(
    baseline: FormalArmResult,
    candidate: FormalArmResult,
) -> list[CaseComparison]:
    left = {case.case_id: case for case in baseline.cases}
    right = {case.case_id: case for case in candidate.cases}
    return [
        CaseComparison(
            case_id=case_id,
            category=left[case_id].category,
            baseline_answer=left[case_id].answer,
            candidate_answer=right[case_id].answer,
            task_success_delta=right[case_id].task_success - left[case_id].task_success,
            latency_delta_ms=right[case_id].latency_ms - left[case_id].latency_ms,
            cost_delta_usd=right[case_id].cost_usd - left[case_id].cost_usd,
        )
        for case_id in sorted(left)
    ]


__all__ = [
    "DatasetIntegrityError",
    "ProductExperimentResult",
    "run_experiment",
]
