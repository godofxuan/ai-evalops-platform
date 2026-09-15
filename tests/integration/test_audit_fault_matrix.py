"""Frozen 20x2 synthetic durable experiment. No model calls or real user data."""

import asyncio
import hashlib
import json
import multiprocessing
import os
import time
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.domain.enums import JobStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    ArtifactReference,
    AuditEvent,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProductExperiment,
    Tenant,
)
from app.product_experiments.client import ProductAPIClient
from app.product_experiments.durable_bundle import verify_durable_bundle, write_durable_bundle
from app.product_experiments.submission import DurableExperimentRequest
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from scripts.prepare_product_client_demo import prepare_dataset
from tests.product_http_support import (
    FixtureResolver,
    LoopbackTargetService,
    LoopbackTargetTransport,
)
from tests.product_worker_process import run_crash_worker

ROOT = Path(__file__).resolve().parents[2]


def _write_new(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)


@pytest.mark.integration
async def test_frozen_twenty_case_two_arm_fault_matrix(tmp_path: Path) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("requires explicit isolated migrated PostgreSQL and Redis")
    evidence = Path(os.getenv("EVALOPS_AUDIT_EVIDENCE_DIR", str(tmp_path / "evidence")))
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=False)
    protocol = (ROOT / "docs/reviews/audit-remediation-20260915/SYNTHETIC_PROTOCOL.md").read_bytes()
    _write_new(
        evidence / "frozen-protocol.json",
        {
            "protocol_sha256": hashlib.sha256(protocol).hexdigest(),
            "planned_jobs": 40,
            "expected": {
                "accepted": 24,
                "failed": 12,
                "cancelled": 4,
                "attempts": 39,
                "http_calls": 39,
            },
            "quality_experiment": False,
            "model_calls": 0,
        },
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(os.environ["EVALOPS_DATABASE_URL"]),
        redis_url=SecretStr(os.environ["EVALOPS_REDIS_URL"]),
        artifact_root=tmp_path / "objects",
        product_experiment_submission_enabled=True,
        product_execution_code_sha=os.getenv("EVALOPS_TEST_CODE_SHA", "e" * 40),
        http_target_registry={
            label: {
                "version": "v1",
                "config": {
                    "base_url": "https://rag.example.com",
                    "endpoint": "/query",
                    "timeout_seconds": 1.0,
                },
            }
            for label in ("baseline", "candidate")
        },
        alembic_config_path=ROOT / "alembic.ini",
    )
    application = create_app(settings=settings)
    tenant, key = uuid4(), uuid4()
    credential = generate_api_key()
    async with application.router.lifespan_context(application):
        factory = cast(AsyncSessionFactory, application.state.session_factory)
        try:
            async with factory.begin() as session:
                session.add(Tenant(id=tenant, slug=f"matrix-{tenant.hex}", name="Synthetic matrix"))
                await session.flush()
                session.add(
                    APIKey(
                        id=key,
                        tenant_id=tenant,
                        name="matrix",
                        key_prefix=credential.prefix,
                        key_hash=credential.key_hash,
                    )
                )
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="https://evalops.example",
                ) as api,
                ProductAPIClient(
                    "https://evalops.example", credential.plaintext.get_secret_value(), http=api
                ) as sdk,
            ):
                await _exercise_matrix(factory, sdk, settings, evidence)
        finally:
            # Scope every cleanup to this fixture tenant; failed artifacts/logs remain.
            async with factory.begin() as session:
                await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant))
                await session.execute(
                    delete(ProductExperiment).where(ProductExperiment.tenant_id == tenant)
                )
                await session.execute(
                    delete(EvaluationRun).where(EvaluationRun.tenant_id == tenant)
                )
                await session.execute(
                    delete(DatasetVersion).where(DatasetVersion.tenant_id == tenant)
                )
                await session.execute(delete(Dataset).where(Dataset.tenant_id == tenant))
                await session.execute(
                    delete(ArtifactReference).where(ArtifactReference.tenant_id == tenant)
                )
                await session.execute(delete(APIKey).where(APIKey.tenant_id == tenant))
                await session.execute(delete(Tenant).where(Tenant.id == tenant))


async def _exercise_matrix(
    factory: AsyncSessionFactory, sdk: ProductAPIClient, settings: Settings, evidence: Path
) -> None:
    raw = json.dumps(
        [
            {
                "case_id": f"case-{index:02}",
                "category": "synthetic",
                "prompt": f"case-{index:02}",
                "reference_answer": "private answer",
                "expected_citation_ids": ["gold"],
                "allowed_tools": [],
                "max_tool_calls": 0,
            }
            for index in range(20)
        ]
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    version = await prepare_dataset(
        sdk,
        raw_dataset=raw,
        expected_sha256=digest,
        output_dir=evidence / "input",
        name="frozen-matrix",
    )
    request = DurableExperimentRequest.model_validate_json(
        json.dumps(
            {
                "schema_version": "evalops.durable-experiment-request/1.0",
                "experiment_id": "synthetic-fault-matrix-v1",
                "task_type": "AGENT_TOOL_USE",
                "dataset_version_id": str(version.id),
                "source_dataset_sha256": digest,
                **{
                    label: {
                        "target_id": label,
                        "target_version": "v1",
                        "source_repository": f"demo://{label}",
                        "source_sha": ("b" if label == "baseline" else "c") * 40,
                    }
                    for label in ("baseline", "candidate")
                },
                "policy": {
                    "schema_version": "formal-agent-quality-policy/1.0",
                    "minimum_common_cases": 100,
                    "minimum_cases_per_category": 10,
                    "required_categories": ["synthetic"],
                    "bootstrap_resamples": 100,
                    "bootstrap_seed": 1,
                    "task_success_ci_lower_min": 0.0,
                    "citation_correctness_ci_lower_min": 0.0,
                    "tool_error_rate_ci_upper_max": 0.0,
                    "latency_p95_relative_delta_max": 1.0,
                    "cost_mean_relative_delta_max": 1.0,
                },
                "max_attempts": 2,
                "max_total_attempts": 80,
                "execution_timeout_seconds": 180.0,
            }
        )
    )
    pair = await sdk.submit(request=request, dataset_payload=raw, idempotency_key="matrix-v1")
    assert (
        await sdk.submit(request=request, dataset_payload=raw, idempotency_key="matrix-v1")
    ) == pair
    run_ids = (pair.baseline_run_id, pair.candidate_run_id)
    async with factory.begin() as session:
        jobs = list(
            (
                await session.scalars(
                    select(EvaluationJob).where(EvaluationJob.run_id.in_(run_ids))
                )
            ).all()
        )
        for job in jobs:
            job.priority = -int(job.case_id[-2:])
    retry = RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.01, jitter_ratio=0)

    def response_for(index: int) -> dict[str, Any] | bytes:
        received = service.requests[index - 1]
        case = int(received["body"]["question"][-2:])
        response: dict[str, Any] = {
            "answer": "private answer",
            "citations": [{"source_id": "gold"}],
            "trace": {
                "cost_usd": 0.01,
                "tool_calls": [],
                "tool_error": False,
                "terminal_state": "completed",
                "source_terminal_state": "answer",
                "budget_exhausted": False,
            },
        }
        if case == 1:
            response["citations"] = [{"id": "gold"}]
        elif case == 2:
            response["citations"] = [{"source_id": "gold", "id": "gold"}]
        elif case == 3:
            response["citations"] *= 2
        elif case == 4:
            response["citations"].append({"id": "extra"})
        elif case == 5:
            response["answer"] = "wrong answer"
        elif case == 6:
            response["trace"]["tool_error"] = True
        elif case == 8 and received["attempt"] == "1":
            time.sleep(1.5)  # Actual socket timeout, not a raised fake TargetTimeoutError.
        elif case == 9:
            return b"{invalid json"
        elif case == 10:
            response["trace"]["terminal_state"] = "failed"
        elif case == 11:
            response["answer"] = "x" * 100001
        elif case == 12:
            response["trace"].pop("terminal_state")
            response["trace"].pop("source_terminal_state")
        elif case == 13:
            response["citations"] = [{"source_id": "wrong", "id": "gold"}]
        elif case == 14:
            response["citations"] = [{"id": 123}]
        elif case == 15:
            response["citations"] = [{"id": "   "}]
        elif case == 16:
            response["citations"] = [{}]
        return response

    async with (
        LoopbackTargetService(response_for=response_for) as service,
        httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as target_http,
    ):

        def target_factory(kind: str, config: Mapping[str, Any]) -> HTTPRAGTarget:
            assert kind == "http_rag"
            return HTTPRAGTarget(config, client=target_http, resolver=FixtureResolver())

        worker = EvaluationWorker(
            claimer=SQLAlchemyJobClaimer(factory, lease_policy=LeasePolicy(timedelta(seconds=30))),
            result_committer=SQLAlchemyResultCommitter(factory),
            failure_committer=SQLAlchemyFailureCommitter(factory, retry_policy=retry),
            lease_runner=LeaseHeartbeatRunner(
                heartbeat_service=SQLAlchemyHeartbeatService(
                    factory, lease_duration=timedelta(seconds=30)
                ),
                heartbeat_interval_seconds=2,
            ),
            target_factory=target_factory,
        )
        async with factory.begin() as hold_other:
            await hold_other.execute(
                select(EvaluationJob.id)
                .where(
                    EvaluationJob.run_id.in_(run_ids),
                    (EvaluationJob.case_id.in_(("case-18", "case-19")))
                    | (
                        (EvaluationJob.case_id == "case-17")
                        & (EvaluationJob.run_id == pair.candidate_run_id)
                    ),
                )
                .with_for_update()
            )
            async with factory.begin() as hold_crash:
                await hold_crash.execute(
                    select(EvaluationJob.id)
                    .where(
                        EvaluationJob.run_id == pair.baseline_run_id,
                        EvaluationJob.case_id == "case-17",
                    )
                    .with_for_update()
                )
                async with asyncio.timeout(60):
                    while True:
                        async with factory() as session:
                            terminal = await session.scalar(
                                select(func.count())
                                .select_from(EvaluationJob)
                                .where(
                                    EvaluationJob.run_id.in_(run_ids),
                                    EvaluationJob.case_id < "case-17",
                                    EvaluationJob.status.in_(
                                        (JobStatus.SUCCEEDED, JobStatus.FAILED)
                                    ),
                                )
                            )
                        if terminal == 34:
                            break
                        await worker.process_one(worker_id="matrix-normal")
            claim = await _crash_after_http(settings.database_url.get_secret_value(), service.port)
            assert (
                claim.case_payload["case_id"] == "case-17" and claim.run_id == pair.baseline_run_id
            )
            reaper = SQLAlchemyJobReaper(factory, retry_policy=retry)
            async with asyncio.timeout(15):
                while not any(row.job_id == claim.job_id for row in await reaper.reap()):  # noqa: ASYNC110 -- actual DB recovery predicate
                    await asyncio.sleep(0.025)
                # Wait for the *database* retry timestamp before asking a claimer
                # to run while other phase rows are intentionally held. Otherwise
                # its legitimate blocking fallback may wait on our own barrier.
                while True:
                    async with factory() as session:
                        ready = await session.scalar(
                            select(EvaluationJob.next_attempt_at <= func.clock_timestamp()).where(
                                EvaluationJob.id == claim.job_id,
                                EvaluationJob.status == JobStatus.RETRY_WAIT,
                            )
                        )
                    if ready:
                        break
                    await asyncio.sleep(0.025)
                assert await worker.process_one(worker_id="matrix-recovery")
            with pytest.raises(LeaseLostError):
                await SQLAlchemyResultCommitter(factory).commit_success(
                    claim=claim,
                    lease_version=claim.version,
                    target_result=TargetResult("stale", (), (), {}, None, 0),
                    evaluation_result=EvaluationResult({"stale": True}),
                )
        assert await worker.process_one(worker_id="matrix-candidate-control")
        assert service.requests[-1]["body"]["question"] == "case-17"
        await sdk.cancel(pair.id)
    report = await sdk.export(pair.id, include_private=True)
    public = await sdk.export(pair.id)
    assert await sdk.export(pair.id, include_private=True) == report
    private_verification = write_durable_bundle(
        report, output_dir=evidence / "private", raw_dataset=raw
    )
    public_verification = write_durable_bundle(public, output_dir=evidence / "public")
    assert private_verification.verification_scope == "PRIVATE_RECOMPUTED"
    assert public_verification.verification_scope == "PUBLIC_PROJECTION_ONLY"
    assert verify_durable_bundle(evidence / "private") == private_verification
    decoded = json.loads(report)
    assert (
        decoded["result"]["case_count"] == 20 and decoded["result"]["status"] == "EXECUTION_FAILED"
    )
    rows = [row for arm in decoded["result_snapshot"]["arms"].values() for row in arm["jobs"]]
    assert len(rows) == 40 and len({row["job_id"] for row in rows}) == 40
    counts = Counter(row["job_status"] for row in rows)
    assert counts == {"succeeded": 24, "failed": 12, "cancelled": 4}, counts
    assert sum(row["attempt_count"] for row in rows) == 39
    assert len(service.requests) == 39
    calls = Counter(row["job_id"] for row in service.requests)
    assert len({row["result_id"] for row in rows if row["result_id"] is not None}) == 24
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JobAttempt)
                .where(JobAttempt.job_id.in_([UUID(row["job_id"]) for row in rows]))
            )
            == 39
        )
    _write_new(
        evidence / "matrix-results.json",
        {
            "status": "SYNTHETIC_PLATFORM_VERIFIED",
            "quality_status": "EXECUTION_FAILED",
            "planned_jobs": 40,
            "counts": dict(counts),
            "attempts": 39,
            "http_calls": 39,
            "model_calls": 0,
            "tls_dns_scope": "INJECTED_FIXTURE_NOT_PUBLIC_TLS_PROOF",
            "private_verification": private_verification.verification_scope,
            "public_verification": public_verification.verification_scope,
            "rows": [
                {
                    **{
                        key: row[key]
                        for key in (
                            "job_id",
                            "case_id",
                            "job_status",
                            "attempt_count",
                            "error_code",
                        )
                    },
                    "http_calls": calls[row["job_id"]],
                }
                for row in rows
            ],
        },
    )
    print(
        "SYNTHETIC_MATRIX_VERIFIED planned=40 accepted=24 failed=12 "
        "cancelled=4 attempts=39 calls=39"
    )


async def _crash_after_http(database_url: str, port: int) -> ClaimedJob:
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    child = context.Process(
        target=run_crash_worker, args=(database_url, port, "after_http", sending), daemon=True
    )
    try:
        child.start()
        sending.close()
        assert await asyncio.to_thread(receiving.poll, 20), "child did not reach HTTP barrier"
        claim = receiving.recv()
        assert isinstance(claim, ClaimedJob), repr(claim)
        assert child.is_alive()
        child.kill()
        await asyncio.to_thread(child.join, 10)
        assert not child.is_alive() and child.exitcode != 0
        return claim
    finally:
        if child.pid is not None:
            if child.is_alive():
                child.kill()
            await asyncio.to_thread(child.join, 10)
            child.close()
        receiving.close()
        sending.close()
