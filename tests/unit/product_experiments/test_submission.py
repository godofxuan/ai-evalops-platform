import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.artifacts.storage import LocalArtifactStore
from app.auth.principals import Principal
from app.product_experiments.dataset_mapping import map_product_dataset
from app.runs.idempotency import canonical_request_hash
from app.runs.repository import DatasetVersionSource
from app.runs.service import SQLAlchemyRunService


class DatasetBoundary:
    def __init__(self, tenant: Any, version: Any, digest: str) -> None:
        self.tenant, self.version, self.digest = tenant, version, digest

    async def get_dataset_version_source(self, *, tenant_id: Any, dataset_version_id: Any) -> Any:
        if (tenant_id, dataset_version_id) != (self.tenant, self.version):
            return None
        return DatasetVersionSource(self.version, self.digest, 2)

    async def create_or_replay(self, _pending: Any) -> Any:
        raise AssertionError("experiment preparation must not persist an individual Run")


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 7, tzinfo=UTC)


@pytest.fixture
async def submission_inputs(tmp_path: Path) -> dict[str, Any]:
    from app.product_experiments.submission import DurableExperimentRequest

    raw = json.dumps(
        [
            {
                "case_id": str(index),
                "category": "qa",
                "prompt": "q",
                "reference_answer": "private answer",
                "expected_citation_ids": ["gold"],
                "metadata": {"public_context": {"locale": "zh-CN"}},
            }
            for index in range(2)
        ]
    ).encode()
    raw_sha = hashlib.sha256(raw).hexdigest()
    mapped = map_product_dataset(raw, expected_sha256=raw_sha)
    store = LocalArtifactStore(tmp_path)
    await store.put_bytes(mapped.dataset.content)
    tenant, version = uuid4(), uuid4()
    principal = Principal(tenant_id=tenant, api_key_id=uuid4(), key_prefix="test")
    service = SQLAlchemyRunService(
        repository=DatasetBoundary(tenant, version, mapped.dataset.sha256),
        artifact_store=store,
        http_target_registry={
            label: {
                "version": "v1",
                "config": {
                    "base_url": "https://rag.example.com",
                    "endpoint": "/query",
                    "include_metadata": True,
                },
            }
            for label in ("baseline", "candidate")
        },
    )
    request = DurableExperimentRequest.model_validate_json(
        json.dumps(
            {
                "schema_version": "evalops.durable-experiment-request/1.0",
                "experiment_id": "paired-qa",
                "task_type": "QA",
                "scope": "DEMO",
                "dataset_version_id": str(version),
                "source_dataset_sha256": raw_sha,
                "baseline": {
                    "target_id": "baseline",
                    "target_version": "v1",
                    "source_repository": "demo://baseline",
                    "source_sha": "b" * 40,
                },
                "candidate": {
                    "target_id": "candidate",
                    "target_version": "v1",
                    "source_repository": "demo://candidate",
                    "source_sha": "c" * 40,
                },
                "policy": {
                    "schema_version": "formal-agent-quality-policy/1.0",
                    "minimum_common_cases": 100,
                    "minimum_cases_per_category": 10,
                    "required_categories": ["qa"],
                    "bootstrap_resamples": 100,
                    "bootstrap_seed": 1,
                    "task_success_ci_lower_min": 0.0,
                    "citation_correctness_ci_lower_min": 0.0,
                    "tool_error_rate_ci_upper_max": 0.0,
                    "latency_p95_relative_delta_max": 1.0,
                    "cost_mean_relative_delta_max": 1.0,
                },
                "execution_timeout_seconds": 60.0,
                "max_attempts": 2,
                "max_total_attempts": 8,
            }
        )
    )
    return {
        "principal": principal,
        "idempotency_key": "pair",
        "request": request,
        "dataset_payload": raw,
        "run_service": service,
        "evalops_sha": "e" * 40,
        "clock": FixedClock(),
    }


@pytest.mark.asyncio
async def test_preparation_binds_raw_mapping_registry_and_shared_deadline(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.submission import prepare_durable_experiment

    raw_sha = submission_inputs["request"].source_dataset_sha256
    mapped = map_product_dataset(submission_inputs["dataset_payload"], expected_sha256=raw_sha)
    pending = await prepare_durable_experiment(**submission_inputs)
    assert pending.baseline.dataset_hash == pending.candidate.dataset_hash == mapped.dataset.sha256
    assert pending.reserved_target_attempts == 8
    assert pending.baseline.execution_deadline_at == pending.candidate.execution_deadline_at
    assert pending.baseline.execution_deadline_at == FixedClock().now() + timedelta(seconds=60)
    assert pending.baseline.evaluator_type == "product_qa_v2"
    assert pending.snapshot["source_dataset_sha256"] == raw_sha
    assert pending.snapshot["normalized_dataset_sha256"] == mapped.dataset.sha256
    assert pending.snapshot["source_sha_attestation"] == "CLIENT_DECLARED"
    assert pending.snapshot["formal_quality_claim_allowed"] is False
    snapshot = dict(pending.snapshot)
    digest = snapshot.pop("content_sha256")
    assert canonical_request_hash(snapshot) == digest


@pytest.mark.asyncio
async def test_preparation_reserves_one_shared_active_claim_window(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.submission import (
        DurableExperimentRequest,
        prepare_durable_experiment,
    )

    raw = submission_inputs["request"].model_dump(mode="json")
    raw["max_active_jobs"] = 2
    submission_inputs["request"] = DurableExperimentRequest.model_validate_json(json.dumps(raw))
    pending = await prepare_durable_experiment(**submission_inputs)
    assert pending.max_active_jobs == 2
    assert pending.snapshot["admission_budget"] == {
        "max_active_jobs": 2,
        "scope": "BOTH_ARMS_AND_RETRIES",
        "enforcement": "DATABASE_ACTIVE_CLAIMS",
        "physical_upstream_concurrency_guaranteed": False,
    }


@pytest.mark.asyncio
async def test_preparation_reserves_total_normalized_observation_bytes_once_per_job(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.submission import (
        DurableExperimentRequest,
        prepare_durable_experiment,
    )

    raw = submission_inputs["request"].model_dump(mode="json")
    raw["max_observation_bytes"] = 4097
    submission_inputs["request"] = DurableExperimentRequest.model_validate_json(json.dumps(raw))
    pending = await prepare_durable_experiment(**submission_inputs)
    assert pending.baseline.evaluator_config["max_observation_bytes_per_case"] == 1024
    assert pending.candidate.evaluator_config["max_observation_bytes_per_case"] == 1024
    assert pending.snapshot["observation_budget"]["reserved_bytes"] == 4096
    assert pending.snapshot["observation_budget"]["max_observation_bytes"] == 4097
    assert pending.snapshot["observation_budget"]["scope"] == "ACCEPTED_NORMALIZED_OBSERVATIONS"
    with pytest.raises(ValueError, match="observation budget"):
        replace(
            pending,
            baseline=replace(pending.baseline, evaluator_config={"max_attempts": 2}),
            candidate=replace(pending.candidate, evaluator_config={"max_attempts": 2}),
        )


@pytest.mark.asyncio
async def test_preparation_rejects_rehashed_raw_data_not_matching_stored_version(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.submission import prepare_durable_experiment
    from app.runs.service import RunInputIntegrityError

    payload = submission_inputs["dataset_payload"].replace(b'"q"', b'"different"')
    submission_inputs["dataset_payload"] = payload
    submission_inputs["request"].source_dataset_sha256 = hashlib.sha256(payload).hexdigest()
    with pytest.raises(RunInputIntegrityError):
        await prepare_durable_experiment(**submission_inputs)


@pytest.mark.asyncio
async def test_preparation_rejects_unregistered_target_version(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.submission import prepare_durable_experiment
    from app.runs.service import InvalidTargetConfigurationError

    submission_inputs["request"].candidate.target_version = "unregistered"
    with pytest.raises(InvalidTargetConfigurationError):
        await prepare_durable_experiment(**submission_inputs)


@pytest.mark.asyncio
async def test_preparation_rejects_total_attempt_shortfall(
    submission_inputs: dict[str, Any],
) -> None:
    from app.product_experiments.spec import InputLimitError
    from app.product_experiments.submission import prepare_durable_experiment

    submission_inputs["request"].max_total_attempts = 7
    with pytest.raises(InputLimitError, match="attempt budget"):
        await prepare_durable_experiment(**submission_inputs)
