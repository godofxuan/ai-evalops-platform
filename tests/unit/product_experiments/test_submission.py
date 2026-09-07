import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

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


class PairDatabaseBoundary:
    def __init__(self) -> None:
        self.result: Any = None
        self.key: tuple[Any, str] | None = None
        self.created_count = 0

    async def find_by_key(self, *, tenant_id: Any, idempotency_key: str) -> Any:
        return self.result if (tenant_id, idempotency_key) == self.key else None

    async def create_or_replay(self, pending: Any) -> Any:
        from app.product_experiments.persistence import ProductExperimentSnapshot

        assert pending.source_artifact is not None
        assert self.result is None, "replay must not attempt another write"
        self.created_count += 1
        self.key = (pending.tenant_id, pending.idempotency_key)
        self.result = ProductExperimentSnapshot(
            id=uuid4(),
            tenant_id=pending.tenant_id,
            request_hash=pending.request_hash,
            baseline_run_id=uuid4(),
            candidate_run_id=uuid4(),
            snapshot=pending.snapshot,
            cancel_requested=False,
            created_at=FixedClock().now(),
            source_artifact_reference_id=uuid4(),
        )
        return self.result


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


@pytest.fixture
async def authenticated_submission_setup(
    submission_inputs: dict[str, Any],
    tmp_path: Path,
) -> dict[str, Any]:
    from app.auth.api_keys import generate_api_key
    from app.auth.service import APIKeyCandidate
    from app.domain.enums import APIKeyStatus, TenantStatus
    from app.main import create_app
    from app.product_experiments.submission import DurableExperimentSubmitter
    from tests.unit.auth.test_authentication import InMemoryAPIKeyLookup

    application = create_app()
    principal = submission_inputs["principal"]
    credential = generate_api_key()
    application.state.api_key_lookup = InMemoryAPIKeyLookup(
        APIKeyCandidate(
            api_key_id=principal.api_key_id,
            tenant_id=principal.tenant_id,
            key_prefix=credential.prefix,
            key_hash=credential.key_hash,
            api_key_status=APIKeyStatus.ACTIVE,
            tenant_status=TenantStatus.ACTIVE,
            expires_at=None,
        )
    )
    repository = PairDatabaseBoundary()
    application.state.product_experiment_submitter = DurableExperimentSubmitter(
        repository=repository,
        run_service=submission_inputs["run_service"],
        artifact_store=LocalArtifactStore(tmp_path / "http-originals"),
        evalops_sha="e" * 40,
        clock=FixedClock(),
    )
    headers = {
        "Authorization": f"Bearer {credential.plaintext.get_secret_value()}",
        "Idempotency-Key": "pair",
    }
    payload = {
        "request": submission_inputs["request"].model_dump(mode="json"),
        "dataset_base64": base64.b64encode(submission_inputs["dataset_payload"]).decode("ascii"),
    }
    return {
        "application": application,
        "headers": headers,
        "payload": payload,
        "repository": repository,
    }


@pytest.mark.asyncio
async def test_authenticated_http_submission_uses_real_preparer_and_replays_pair(
    authenticated_submission_setup: dict[str, Any],
) -> None:
    application, headers, payload, repository = (
        authenticated_submission_setup[key]
        for key in ("application", "headers", "payload", "repository")
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/experiments", headers=headers, json=payload)
        assert response.status_code == 202
        replay = await client.post("/api/v1/experiments", headers=headers, json=payload)
    assert response.json() == replay.json()
    assert response.json()["id"] == str(repository.result.id)
    assert response.json()["formal_quality_claim_allowed"] is False
    assert "private answer" not in response.text and repository.created_count == 1


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("duplicate", 422),
        ("bad_base64", 422),
        ("source_changed", 422),
        ("invalid_dataset", 422),
        ("unknown_secret", 422),
        ("formal", 422),
        ("compressed", 415),
        ("declared_size", 413),
        ("streamed_size", 413),
        ("disabled", 503),
    ],
)
async def test_invalid_http_submission_does_not_create_pair_or_echo_inputs(
    authenticated_submission_setup: dict[str, Any],
    mode: str,
    expected: int,
) -> None:
    setup = authenticated_submission_setup
    application, payload = setup["application"], setup["payload"]
    headers = {**setup["headers"], "Content-Type": "application/json"}
    canary = "PRIVATE_INPUT_MUST_NOT_APPEAR"
    if mode == "bad_base64":
        payload["dataset_base64"] = "!" + canary
    elif mode == "source_changed":
        payload["dataset_base64"] = base64.b64encode(canary.encode()).decode()
    elif mode == "invalid_dataset":
        raw = json.dumps({"invalid": canary}).encode()
        payload["dataset_base64"] = base64.b64encode(raw).decode()
        payload["request"]["source_dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    elif mode == "unknown_secret":
        payload["request"]["baseline"]["token"] = canary
    elif mode == "formal":
        payload["request"]["scope"] = "FORMAL"
    elif mode == "compressed":
        headers["Content-Encoding"] = "gzip"
    elif mode == "declared_size":
        headers["Content-Length"] = str(16 * 1024 * 1024 + 1)
    elif mode == "disabled":
        application.state.product_experiment_submitter = None
    body: Any = json.dumps(payload).encode()
    if mode == "duplicate":
        body = ('{"dataset_base64":"' + canary + '",' + body.decode()[1:]).encode()
    if mode == "streamed_size":

        async def large_stream():
            yield b"x" * (8 * 1024 * 1024)
            yield b"x" * (8 * 1024 * 1024)
            yield b"x"

        body = large_stream()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/experiments", headers=headers, content=body)
    assert response.status_code == expected
    assert setup["repository"].created_count == 0
    assert canary not in response.text


@pytest.mark.asyncio
async def test_submission_replays_frozen_pair_without_registry_or_storage_reexecution(
    submission_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    from app.product_experiments.submission import DurableExperimentSubmitter
    from app.runs.service import IdempotencyConflictError

    repository = PairDatabaseBoundary()
    submitter = DurableExperimentSubmitter(
        repository=repository,
        run_service=submission_inputs["run_service"],
        artifact_store=LocalArtifactStore(tmp_path / "originals"),
        evalops_sha="e" * 40,
        clock=FixedClock(),
    )
    args = {
        key: submission_inputs[key]
        for key in ("principal", "idempotency_key", "request", "dataset_payload")
    }
    first = await submitter.submit(**args)
    empty_store = LocalArtifactStore(tmp_path / "must-stay-empty")
    replay_submitter = DurableExperimentSubmitter(
        repository=repository,
        run_service=SQLAlchemyRunService(
            repository=DatasetBoundary(uuid4(), uuid4(), "0" * 64),
            artifact_store=empty_store,
            http_target_registry={},
        ),
        artifact_store=empty_store,
        evalops_sha="f" * 40,
        clock=FixedClock(),
    )
    assert await replay_submitter.submit(**args) == first
    assert repository.created_count == 1 and not (tmp_path / "must-stay-empty").exists()
    args["request"] = args["request"].model_copy(update={"max_active_jobs": 1})
    with pytest.raises(IdempotencyConflictError):
        await replay_submitter.submit(**args)


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
async def test_prepared_source_retains_original_bytes_not_normalized_jsonl(
    submission_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    from app.product_experiments.submission import prepare_durable_experiment, retain_durable_source

    pending = await prepare_durable_experiment(**submission_inputs)
    store = LocalArtifactStore(tmp_path / "raw-evidence")
    retained = await retain_durable_source(
        pending=pending, dataset_payload=submission_inputs["dataset_payload"], artifact_store=store
    )
    assert pending.source_artifact is None
    assert retained.source_artifact is not None
    assert retained.source_artifact.sha256 == submission_inputs["request"].source_dataset_sha256
    assert retained.source_artifact.sha256 != retained.baseline.dataset_hash
    assert (
        await store.get_bytes(retained.source_artifact.sha256)
        == submission_inputs["dataset_payload"]
    )


@pytest.mark.asyncio
async def test_source_changed_after_preparation_is_not_published(
    submission_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    from app.product_experiments.submission import prepare_durable_experiment, retain_durable_source
    from app.runs.service import RunInputIntegrityError

    pending = await prepare_durable_experiment(**submission_inputs)
    root = tmp_path / "must-not-be-published"
    with pytest.raises(RunInputIntegrityError):
        await retain_durable_source(
            pending=pending,
            dataset_payload=submission_inputs["dataset_payload"] + b" ",
            artifact_store=LocalArtifactStore(root),
        )
    assert not root.exists()


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
