"""Public submission → real worker death → lease recovery → immutable, recomputable report."""

import asyncio
import base64
import multiprocessing
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.strict_json import decode_evidence_json
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import AsyncSessionFactory
from app.product_experiments.client import ProductAPIClient
from app.product_experiments.durable_verification import verify_durable_report
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from tests.product_http_support import (
    FixtureResolver,
    LoopbackTargetService,
    LoopbackTargetTransport,
)
from tests.product_worker_process import run_crash_worker


async def exercise_product_process_recovery(
    application: FastAPI, api: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    factory = cast(AsyncSessionFactory, application.state.session_factory)
    settings = cast(Settings, application.state.settings)
    for phase in ("claimed", "after_http"):
        submitted = await api.post(
            "/api/v1/experiments",
            json=payload,
            headers={**headers, "Idempotency-Key": f"crash-pair-{phase}"},
        )
        assert submitted.status_code == 202
        experiment_id = UUID(submitted.json()["id"])
        async with (
            LoopbackTargetService() as service,
            httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as client,
        ):

            def target_factory(kind: str, config: Mapping[str, Any]) -> HTTPRAGTarget:
                assert kind == "http_rag"
                return HTTPRAGTarget(config, client=client, resolver=FixtureResolver())

            worker = EvaluationWorker(
                claimer=SQLAlchemyJobClaimer(
                    factory, lease_policy=LeasePolicy(timedelta(seconds=60))
                ),
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
            # One accepted result exists before the crash and must never be called again.
            assert await worker.process_one(worker_id=f"before-crash-{phase}")
            completed_job = service.requests[0]["job_id"]
            context = multiprocessing.get_context("spawn")
            receiving, sending = context.Pipe(duplex=False)
            process = context.Process(
                target=run_crash_worker,
                args=(settings.database_url.get_secret_value(), service.port, phase, sending),
                daemon=True,
            )
            try:
                process.start()
                sending.close()
                assert await asyncio.to_thread(receiving.poll, 20), (
                    "worker did not reach death barrier"
                )
                claim = receiving.recv()
                assert isinstance(claim, ClaimedJob), (
                    "worker failed before controlled death barrier"
                )
                assert str(claim.run_id) in {
                    submitted.json()["baseline_run_id"],
                    submitted.json()["candidate_run_id"],
                }
                assert str(claim.job_id) != completed_job
                assert process.is_alive()
                process.kill()  # This is only the exact child created above, never an external PID.
                await asyncio.to_thread(process.join, 10)
                assert not process.is_alive() and process.exitcode != 0
            finally:
                if process.pid is not None:
                    if process.is_alive():
                        process.kill()
                    await asyncio.to_thread(process.join, 10)
                    process.close()
                receiving.close()
                sending.close()

            reaper = SQLAlchemyJobReaper(
                factory,
                retry_policy=RetryPolicy(
                    base_delay_seconds=0.01, max_delay_seconds=0.01, jitter_ratio=0
                ),
            )
            # Poll the actual expiration/reaper state, not a guessed long sleep or forged DB clock.
            async with asyncio.timeout(15):
                while True:
                    reaped = await reaper.reap()
                    if any(row.job_id == claim.job_id for row in reaped):
                        assert (
                            next(row for row in reaped if row.job_id == claim.job_id).action
                            == "requeued"
                        )
                        break
                    await asyncio.sleep(0.025)
                completed = 0
                while completed < 3:
                    if await worker.process_one(worker_id=f"recovered-{phase}"):
                        completed += 1
                    else:
                        await asyncio.sleep(0.025)
            assert not await worker.process_one(worker_id=f"drained-{phase}")
            counts = Counter(row["job_id"] for row in service.requests)
            assert len(counts) == 4 and counts[completed_job] == 1
            assert counts[str(claim.job_id)] == (2 if phase == "after_http" else 1)
            assert all(row["body"] == {"question": "q"} for row in service.requests)
            crashed_attempts = [
                row["attempt"] for row in service.requests if row["job_id"] == str(claim.job_id)
            ]
            assert crashed_attempts == (["1", "2"] if phase == "after_http" else ["2"])

        with pytest.raises(LeaseLostError):
            await SQLAlchemyResultCommitter(factory).commit_success(
                claim=claim,
                lease_version=claim.version,
                target_result=TargetResult("stale poison", (), (), {}, None, 0),
                evaluation_result=EvaluationResult({"stale_poison": True}),
            )
        async with ProductAPIClient(
            "https://evalops.example", headers["Authorization"].removeprefix("Bearer "), http=api
        ) as sdk:
            assert (await sdk.get(experiment_id)).state == "READY_FOR_ASSESSMENT"
            report = await sdk.export(experiment_id, include_private=True)
            verified = verify_durable_report(
                report,
                raw_dataset=base64.b64decode(payload["dataset_base64"], validate=True),
                experiment_id=experiment_id,
            )
            assert verified.verification_scope == "PRIVATE_RECOMPUTED"
            assert verified.quality_status == "INSUFFICIENT_EVIDENCE"
            decoded = decode_evidence_json(report)
            accepted_jobs = [
                job for arm in decoded["result_snapshot"]["arms"].values() for job in arm["jobs"]
            ]
            assert len(accepted_jobs) == 4 and len({job["result_id"] for job in accepted_jobs}) == 4
            recovered_job = next(job for job in accepted_jobs if job["job_id"] == str(claim.job_id))
            assert recovered_job["accepted_attempt_number"] == 2
            assert recovered_job["accepted_attempt_id"] != str(claim.attempt_id)
            assert all(
                job["accepted_attempt_number"] == 1
                for job in accepted_jobs
                if job is not recovered_job
            )
            assert await sdk.export(experiment_id, include_private=True) == report
