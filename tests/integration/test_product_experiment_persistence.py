import asyncio
import base64
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from pydantic import SecretStr
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from app.artifacts.repository import SQLAlchemyArtifactReferenceGateway
from app.artifacts.service import ArtifactAccessService, ArtifactReferenceNotFoundError
from app.artifacts.storage import DeletableArtifactStore
from app.auth.api_keys import generate_api_key
from app.auth.principals import Principal
from app.core.config import Settings
from app.domain.enums import RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    ArtifactReference,
    AuditEvent,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProductExperiment,
    Tenant,
)
from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.dataset_mapping import map_product_dataset
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.persistence import (
    NewProductExperiment,
    SQLAlchemyProductExperimentRepository,
)
from app.product_experiments.report_persistence import (
    ReportPublicationConflictError,
    SQLAlchemyProductReportRepository,
)
from app.product_experiments.result_snapshot import (
    ExperimentNotTerminalError,
    SQLAlchemyProductResultReader,
)
from app.runs.idempotency import canonical_request_hash
from app.runs.schemas import RunCreate
from app.runs.service import IdempotencyConflictError, SQLAlchemyRunService
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from tests.postgres_test_support import wait_for_lock_sensitive
from tests.product_process_recovery import exercise_product_process_recovery

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_real_postgres_pair_idempotency_and_hidden_tenant_boundary(tmp_path: Path) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("requires isolated migrated PostgreSQL")
    database_url = os.environ["EVALOPS_DATABASE_URL"]
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(os.environ["EVALOPS_REDIS_URL"]),
        artifact_root=tmp_path,
        product_experiment_submission_enabled=True,
        product_execution_code_sha="e" * 40,
        http_target_registry={
            label: {
                "version": "v1",
                "config": {"base_url": "https://rag.example.com", "endpoint": "/query"},
            }
            for label in ("baseline", "candidate")
        },
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
    )
    application = create_app(settings=settings)
    tenant_id, key_id = uuid4(), uuid4()
    credential = generate_api_key()
    other_tenant_id, other_key_id = uuid4(), uuid4()
    other_credential = generate_api_key()
    async with application.router.lifespan_context(application):
        factory = cast(AsyncSessionFactory, application.state.session_factory)
        async with factory.begin() as session:
            session.add(
                Tenant(
                    id=other_tenant_id,
                    slug=f"pair-other-{other_tenant_id.hex}",
                    name="Other pair tenant",
                )
            )
            session.add(Tenant(id=tenant_id, slug=f"pair-{tenant_id.hex}", name="Pair test"))
            await session.flush()
            session.add(
                APIKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    name="pair-test",
                    key_prefix=credential.prefix,
                    key_hash=credential.key_hash,
                )
            )
            session.add(
                APIKey(
                    id=other_key_id,
                    tenant_id=other_tenant_id,
                    name="other-pair-test",
                    key_prefix=other_credential.prefix,
                    key_hash=other_credential.key_hash,
                )
            )
        headers = {"Authorization": f"Bearer {credential.plaintext.get_secret_value()}"}
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/datasets", headers=headers, json={"name": "pair"})
            assert response.status_code == 201
            dataset_id = response.json()["id"]
            content = (
                b'{"case_id":"q1","question":"q","expected_answer":"a","metadata":{}}\n'
                b'{"case_id":"q2","question":"q","expected_answer":"a","metadata":{}}\n'
            )
            response = await client.post(
                f"/api/v1/datasets/{dataset_id}/versions",
                headers=headers,
                files={"file": ("cases.jsonl", content, "application/x-ndjson")},
            )
            assert response.status_code == 201
            dataset_version = UUID(response.json()["id"])
        service = cast(SQLAlchemyRunService, application.state.run_service)
        principal = Principal(tenant_id=tenant_id, api_key_id=key_id, key_prefix=credential.prefix)
        request = RunCreate.model_validate(
            {
                "dataset_version_id": str(dataset_version),
                "target": {"type": "mock", "version": "v1"},
                "evaluator": {"type": "basic_answer", "version": "builtin-v1"},
            }
        )
        baseline = await service.prepare_run(
            principal=principal, idempotency_key="b", request=request
        )
        deadline = datetime(2030, 1, 1, tzinfo=UTC)
        baseline = replace(baseline, execution_deadline_at=deadline)
        candidate = replace(baseline, idempotency_key="c", target_version="v2")
        raw_source = b'{"fixture":"original input bytes, not normalized JSONL"}'
        artifact_store = cast(DeletableArtifactStore, application.state.artifact_store)
        source_artifact = await artifact_store.put_bytes(raw_source)
        pending = NewProductExperiment(
            tenant_id=tenant_id,
            created_by=key_id,
            idempotency_key="same-pair",
            request_hash="a" * 64,
            snapshot={
                "schema_version": "integration-only",
                "source_dataset_sha256": source_artifact.sha256,
            },
            baseline=baseline,
            candidate=candidate,
            source_artifact=source_artifact,
        )
        repository = SQLAlchemyProductExperimentRepository(factory)
        results = await asyncio.gather(*(repository.create_or_replay(pending) for _ in range(8)))
        assert len({result.id for result in results}) == 1
        pair = results[0]
        with pytest.raises(ExperimentNotTerminalError):
            await SQLAlchemyProductResultReader(factory).read(
                tenant_id=tenant_id, experiment_id=pair.id
            )
        assert pair.source_artifact_reference_id is not None
        source_access = ArtifactAccessService(
            gateway=SQLAlchemyArtifactReferenceGateway(factory), store=artifact_store
        )
        assert (
            await source_access.read_bytes(
                tenant_id=tenant_id, reference_id=pair.source_artifact_reference_id
            )
            == raw_source
        )
        with pytest.raises(ArtifactReferenceNotFoundError):
            await source_access.read_bytes(
                tenant_id=other_tenant_id, reference_id=pair.source_artifact_reference_id
            )
        assert pair.snapshot["attempt_budget"] == {
            "schema_version": "evalops.static-attempt-budget/1.0",
            "max_total_attempts": 20_000,
            "reserved_target_attempts": 12,
            "enforcement": "EXISTING_PER_JOB_ATTEMPT_LIMITS",
            "model_internal_calls_bounded": False,
            "hard_currency_budget": False,
        }
        assert pair.baseline_run_id != pair.candidate_run_id
        frozen_snapshot = dict(pair.snapshot)
        snapshot_digest = frozen_snapshot.pop("content_sha256")
        assert canonical_request_hash(frozen_snapshot) == snapshot_digest
        async with factory() as session:
            deadlines = (
                (
                    await session.execute(
                        select(EvaluationRun.execution_deadline_at).where(
                            EvaluationRun.tenant_id == tenant_id,
                            EvaluationRun.id.in_((pair.baseline_run_id, pair.candidate_run_id)),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert deadlines == [deadline, deadline]
        assert await repository.get(tenant_id=uuid4(), experiment_id=pair.id) is None
        assert (await repository.get(tenant_id=tenant_id, experiment_id=pair.id)) == pair
        with pytest.raises(IdempotencyConflictError):
            await repository.create_or_replay(replace(pending, request_hash="b" * 64))
        inserted_versions: list[str] = []

        def fail_second_arm(
            _mapper: Mapper[EvaluationRun], _connection: Connection, target: EvaluationRun
        ) -> None:
            inserted_versions.append(target.target_version)
            if target.target_version == "v2":
                raise RuntimeError("injected second-arm insert failure")

        event.listen(EvaluationRun, "before_insert", fail_second_arm)
        try:
            with pytest.raises(RuntimeError, match="second-arm"):
                await repository.create_or_replay(replace(pending, idempotency_key="rollback-pair"))
        finally:
            event.remove(EvaluationRun, "before_insert", fail_second_arm)
        assert inserted_versions == ["v1", "v2"]
        assert (
            await repository.find_by_key(tenant_id=tenant_id, idempotency_key="rollback-pair")
            is None
        )
        async with factory() as session:
            runs = (
                (
                    await session.execute(
                        select(EvaluationRun.id).where(EvaluationRun.tenant_id == tenant_id)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                (
                    await session.execute(
                        select(EvaluationJob.id).where(EvaluationJob.run_id.in_(runs))
                    )
                )
                .scalars()
                .all()
            )
        assert len(runs) == 2 and len(jobs) == 4
        async with factory() as session:
            source_refs = list(
                (
                    await session.scalars(
                        select(ArtifactReference.id).where(
                            ArtifactReference.tenant_id == tenant_id,
                            ArtifactReference.blob_sha256 == source_artifact.sha256,
                        )
                    )
                ).all()
            )
        # Replays and second-arm rollback must not leave extra source ownership records.
        assert source_refs == [pair.source_artifact_reference_id]
        other_headers = {"Authorization": f"Bearer {other_credential.plaintext.get_secret_value()}"}
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            own = await client.get(f"/api/v1/experiments/{pair.id}", headers=headers)
            assert own.status_code == 200 and own.json()["state"] == "QUEUED"
            cross = await client.get(f"/api/v1/experiments/{pair.id}", headers=other_headers)
            assert cross.status_code == 404
            cross_cancel = await client.post(
                f"/api/v1/experiments/{pair.id}/cancel", headers=other_headers
            )
            assert cross_cancel.status_code == 404
            cancelled_response = await client.post(
                f"/api/v1/experiments/{pair.id}/cancel", headers=headers
            )
            assert cancelled_response.status_code == 202
            assert cancelled_response.json()["state"] == "CANCELLED"
            assert cancelled_response.json()["formal_quality_claim_allowed"] is False
        outsider = replace(principal, tenant_id=uuid4())
        assert await repository.cancel(principal=outsider, experiment_id=pair.id) is None
        cancelled = await repository.cancel(principal=principal, experiment_id=pair.id)
        assert cancelled is not None and cancelled.cancel_requested
        assert await repository.cancel(principal=principal, experiment_id=pair.id) == cancelled
        for run_id in (pair.baseline_run_id, pair.candidate_run_id):
            assert (
                await service.get_run(principal=principal, run_id=run_id)
            ).status == RunStatus.CANCELLED
        await exercise_shared_admission(factory, repository, pending, artifact_store)
        await exercise_authenticated_submission(application, dataset_id, headers, other_headers)
        async with factory.begin() as session:
            runs = list(
                (
                    await session.scalars(
                        select(EvaluationRun.id).where(EvaluationRun.tenant_id == tenant_id)
                    )
                ).all()
            )
            await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
            await session.execute(delete(CaseResult).where(CaseResult.run_id.in_(runs)))
            await session.execute(
                delete(JobAttempt).where(
                    JobAttempt.job_id.in_(
                        select(EvaluationJob.id).where(EvaluationJob.run_id.in_(runs))
                    )
                )
            )
            await session.execute(
                delete(ProductExperiment).where(ProductExperiment.tenant_id == tenant_id)
            )
            await session.execute(delete(EvaluationJob).where(EvaluationJob.run_id.in_(runs)))
            await session.execute(delete(EvaluationRun).where(EvaluationRun.tenant_id == tenant_id))
            await session.execute(
                delete(DatasetVersion).where(DatasetVersion.dataset_id == UUID(dataset_id))
            )
            await session.execute(delete(Dataset).where(Dataset.id == UUID(dataset_id)))
            await session.execute(
                delete(ArtifactReference).where(ArtifactReference.tenant_id == tenant_id)
            )
            await session.execute(delete(APIKey).where(APIKey.id == key_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(APIKey).where(APIKey.id == other_key_id))
            await session.execute(delete(Tenant).where(Tenant.id == other_tenant_id))


async def exercise_authenticated_submission(
    application: FastAPI,
    dataset_id: str,
    headers: dict[str, str],
    other_headers: dict[str, str],
) -> None:
    """Use real lifespan services, authentication, storage and PostgreSQL through HTTP."""
    raw = json.dumps(
        [
            {
                "case_id": str(index),
                "category": "qa",
                "prompt": "q",
                "reference_answer": "private answer",
                "expected_citation_ids": ["gold"],
            }
            for index in range(2)
        ]
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    mapped = map_product_dataset(raw, expected_sha256=digest)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        version = await client.post(
            f"/api/v1/datasets/{dataset_id}/versions",
            headers=headers,
            files={"file": ("product.jsonl", mapped.dataset.content, "application/x-ndjson")},
        )
        assert version.status_code == 201
        request = {
            "schema_version": "evalops.durable-experiment-request/1.0",
            "experiment_id": "http-pair",
            "task_type": "QA",
            "scope": "DEMO",
            "dataset_version_id": version.json()["id"],
            "source_dataset_sha256": digest,
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
        }
        payload = {"request": request, "dataset_base64": base64.b64encode(raw).decode()}
        submit_headers = {**headers, "Idempotency-Key": "real-http-pair"}
        outsider = await client.post(
            "/api/v1/experiments",
            json=payload,
            headers={**other_headers, "Idempotency-Key": "outsider-pair"},
        )
        assert outsider.status_code == 404
        responses = await wait_for_lock_sensitive(
            asyncio.gather(
                *(
                    client.post("/api/v1/experiments", headers=submit_headers, json=payload)
                    for _ in range(8)
                )
            ),
            operation="authenticated concurrent product submissions",
        )
        assert all(response.status_code == 202 for response in responses)
        accepted = responses[0].json()
        assert all(response.json() == accepted for response in responses)
        assert accepted["formal_quality_claim_allowed"] is False
        assert "private answer" not in responses[0].text
        status = await client.get(accepted["status_url"], headers=headers)
        assert status.status_code == 200 and status.json()["state"] == "QUEUED"
        not_ready = await client.post(accepted["status_url"] + "/export", headers=headers)
        assert not_ready.status_code == 409
        hidden_export = await client.post(accepted["status_url"] + "/export", headers=other_headers)
        assert hidden_export.status_code == 404
        hidden = await client.get(accepted["status_url"], headers=other_headers)
        assert hidden.status_code == 404
        altered = {**payload, "request": {**request, "max_active_jobs": 1}}
        conflict = await client.post("/api/v1/experiments", headers=submit_headers, json=altered)
        assert conflict.status_code == 409
        cancelled = await client.post(accepted["status_url"] + "/cancel", headers=headers)
        assert cancelled.status_code == 202 and cancelled.json()["state"] == "CANCELLED"
        replay = await client.post("/api/v1/experiments", headers=submit_headers, json=payload)
        assert replay.status_code == 202 and replay.json() == accepted
        final = await client.get(accepted["status_url"], headers=headers)
        assert final.json()["state"] == "CANCELLED"
        cancelled_report = await client.post(accepted["status_url"] + "/export", headers=headers)
        assert cancelled_report.status_code == 200
        assert cancelled_report.json()["summary"]["status"] == "EXECUTION_FAILED"
        assert "private answer" not in cancelled_report.text
        await exercise_worker_to_export(application, client, headers, other_headers, payload)
        await exercise_product_process_recovery(application, client, headers, payload)


async def exercise_worker_to_export(
    application: FastAPI,
    client: AsyncClient,
    headers: dict[str, str],
    other_headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    """Actual API/worker/PostgreSQL/artifacts; only upstream HTTP/DNS/peer are fixtures."""
    submitted = await client.post(
        "/api/v1/experiments",
        json=payload,
        headers={**headers, "Idempotency-Key": "worker-export-pair"},
    )
    assert submitted.status_code == 202
    accepted = submitted.json()
    observed_requests: list[tuple[str, str]] = []

    class Resolver:
        async def resolve(self, hostname: str) -> tuple[str, ...]:
            assert hostname == "rag.example.com"
            return ("93.184.216.34",)

    class Peer:
        def get_extra_info(self, name: str) -> object:
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def upstream(request: Request) -> Response:
        # Labels and private answers must never be included in the target request.
        assert json.loads(request.content) == {"question": "q"}
        observed_requests.append(
            (request.headers["x-evalops-job-id"], request.headers["x-evalops-attempt"])
        )
        return Response(
            200,
            json={
                "answer": "private answer",
                "citations": [{"source_id": "gold"}],
                "trace": {"cost_usd": 0.01},
            },
            extensions={"network_stream": Peer()},
        )

    factory = cast(AsyncSessionFactory, application.state.session_factory)
    async with AsyncClient(transport=MockTransport(upstream)) as upstream_client:

        def target_factory(kind: str, config: Mapping[str, Any]) -> HTTPRAGTarget:
            assert kind == "http_rag"
            return HTTPRAGTarget(config, client=upstream_client, resolver=Resolver())

        worker = EvaluationWorker(
            claimer=SQLAlchemyJobClaimer(factory, lease_policy=LeasePolicy(timedelta(seconds=60))),
            result_committer=SQLAlchemyResultCommitter(factory),
            failure_committer=SQLAlchemyFailureCommitter(factory, retry_policy=RetryPolicy()),
            lease_runner=LeaseHeartbeatRunner(
                heartbeat_service=SQLAlchemyHeartbeatService(
                    factory, lease_duration=timedelta(seconds=60)
                ),
                heartbeat_interval_seconds=5,
            ),
            target_factory=target_factory,
        )
        for _ in range(4):
            assert await worker.process_one(worker_id="product-export-worker")
        assert not await worker.process_one(worker_id="product-export-worker")
    assert len(observed_requests) == 4 and len({job for job, _ in observed_requests}) == 4
    assert all(attempt == "1" for _, attempt in observed_requests)
    status = await client.get(accepted["status_url"], headers=headers)
    assert status.status_code == 200 and status.json()["state"] == "READY_FOR_ASSESSMENT"
    exports = await wait_for_lock_sensitive(
        asyncio.gather(
            *(client.post(accepted["status_url"] + "/export", headers=headers) for _ in range(8))
        ),
        operation="concurrent authenticated report export",
    )
    assert all(response.status_code == 200 for response in exports)
    assert all(response.content == exports[0].content for response in exports)
    public = exports[0].json()
    assert public["summary"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "private answer" not in exports[0].text
    private = await client.post(
        accepted["status_url"] + "/export?include_private=true", headers=headers
    )
    assert private.status_code == 200
    assert hashlib.sha256(private.content).hexdigest() == public["private_report_sha256"]
    result = private.json()["result"]
    assert len(result["case_comparisons"]) == 2
    assert {event["job_id"] for event in result["execution_events"]} == {
        job for job, _ in observed_requests
    }
    assert len(observed_requests) == 4  # Export did not recall the closed target client.
    hidden = await client.post(
        accepted["status_url"] + "/export?include_private=true", headers=other_headers
    )
    assert hidden.status_code == 404

    experiment_id = UUID(accepted["id"])
    async with ProductAPIClient(
        "https://evalops.example", headers["Authorization"].removeprefix("Bearer "), http=client
    ) as sdk:
        recovered = await sdk.wait(experiment_id, wait_seconds=5)
        assert recovered.state == "READY_FOR_ASSESSMENT"
        assert await sdk.export(experiment_id) == exports[0].content
        downloaded = await sdk.export(experiment_id, include_private=True)
        assert downloaded == private.content
        verified = verify_durable_report(
            downloaded,
            raw_dataset=base64.b64decode(payload["dataset_base64"], validate=True),
            expected_sha256=public["private_report_sha256"],
            experiment_id=experiment_id,
        )
        assert verified.verification_scope == "PRIVATE_RECOMPUTED"
        assert verified.quality_status == "INSUFFICIENT_EVIDENCE"
    async with ProductAPIClient(
        "https://evalops.example",
        other_headers["Authorization"].removeprefix("Bearer "),
        http=client,
    ) as outsider:
        with pytest.raises(ProductAPIError, match="^api_http_404$"):
            await outsider.export(experiment_id, include_private=True)
    assert len(observed_requests) == 4


async def exercise_shared_admission(
    factory: AsyncSessionFactory,
    repository: SQLAlchemyProductExperimentRepository,
    pending: NewProductExperiment,
    artifact_store: DeletableArtifactStore,
) -> None:
    """Real eight-worker waves: each pair shares one slot; neither blocks the other."""
    pairs = [
        await repository.create_or_replay(
            replace(pending, idempotency_key=f"window-{index}", max_active_jobs=1)
        )
        for index in range(2)
    ]
    by_run = {
        run_id: pair.id
        for pair in pairs
        for run_id in (pair.baseline_run_id, pair.candidate_run_id)
    }
    claimer = SQLAlchemyJobClaimer(factory, lease_policy=LeasePolicy(timedelta(seconds=60)))
    committer = SQLAlchemyResultCommitter(factory)
    accepted_jobs: set[UUID] = set()
    for wave in range(4):
        batches = await wait_for_lock_sensitive(
            asyncio.gather(
                *(claimer.claim(worker_id=f"window-{wave}-{index}", limit=1) for index in range(8))
            ),
            operation="experiment shared admission wave",
        )
        claims = [claim for batch in batches for claim in batch]
        assert len(claims) == 2
        assert {by_run[claim.run_id] for claim in claims} == {pair.id for pair in pairs}
        assert all(claim.attempt_number == 1 for claim in claims)
        assert not accepted_jobs.intersection(claim.job_id for claim in claims)
        assert await claimer.claim(worker_id="capacity-full", limit=1) == ()
        await wait_for_lock_sensitive(
            asyncio.gather(
                *(
                    committer.commit_success(
                        claim=claim,
                        lease_version=claim.version,
                        target_result=TargetResult(
                            answer="a",
                            citations=(),
                            sources=(),
                            trace={},
                            token_usage=None,
                            latency_ms=1,
                        ),
                        evaluation_result=EvaluationResult(metrics={"execution_success": True}),
                    )
                    for claim in claims
                )
            ),
            operation="release experiment admission slots via accepted results",
        )
        accepted_jobs.update(claim.job_id for claim in claims)
    assert len(accepted_jobs) == 8
    assert await claimer.claim(worker_id="all-pairs-done", limit=1) == ()
    reader = SQLAlchemyProductResultReader(factory)
    for pair in pairs:
        frozen = await reader.read(tenant_id=pending.tenant_id, experiment_id=pair.id)
        assert frozen is not None
        assert await reader.read(tenant_id=pending.tenant_id, experiment_id=pair.id) == frozen
        assert await reader.read(tenant_id=uuid4(), experiment_id=pair.id) is None
        for arm in frozen["arms"].values():
            assert len(arm["jobs"]) == 2
            assert all(job["accepted_attempt_number"] == 1 for job in arm["jobs"])
            assert all(job["accepted_attempt_id"] is not None for job in arm["jobs"])
        unsigned = dict(frozen)
        digest = unsigned.pop("content_sha256")
        assert canonical_request_hash(unsigned) == digest
        report_repository = SQLAlchemyProductReportRepository(factory)
        # This is an artifact transaction fixture, not a product quality report.
        stored = await artifact_store.put_bytes(
            json.dumps({"publication_fixture": digest}).encode()
        )
        principal = Principal(
            tenant_id=pending.tenant_id, api_key_id=pending.created_by, key_prefix="test"
        )
        published = await asyncio.gather(
            *(
                report_repository.publish(principal=principal, snapshot=frozen, stored=stored)
                for _ in range(8)
            )
        )
        assert all(item == published[0] for item in published)
        receipt = published[0]
        assert receipt.content_sha256 == stored.sha256
        assert receipt.snapshot_sha256 == digest
        assert (
            await report_repository.get(tenant_id=pending.tenant_id, experiment_id=pair.id)
            == receipt
        )
        assert await report_repository.get(tenant_id=uuid4(), experiment_id=pair.id) is None
        access = ArtifactAccessService(
            gateway=SQLAlchemyArtifactReferenceGateway(factory), store=artifact_store
        )
        assert (
            await access.read_bytes(
                tenant_id=pending.tenant_id,
                reference_id=receipt.artifact_reference_id,
                run_id=pair.baseline_run_id,
            )
            == json.dumps({"publication_fixture": digest}).encode()
        )
        different = await artifact_store.put_bytes(b"different-publication-fixture")
        with pytest.raises(ReportPublicationConflictError):
            await report_repository.publish(principal=principal, snapshot=frozen, stored=different)
