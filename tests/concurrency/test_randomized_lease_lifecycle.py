"""Frozen 100-seed real PostgreSQL interleavings, not a throughput benchmark."""

import asyncio
import os
import random
from dataclasses import replace
from datetime import timedelta
from time import perf_counter
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.auth.principals import Principal
from app.domain.enums import AttemptOutcome, JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import (
    AttemptNotActiveError,
    ResultAlreadyCommittedError,
    SQLAlchemyResultCommitter,
)
from app.jobs.retry_policy import RetryPolicy
from app.observability.metrics import PlatformMetrics
from app.persistence.orm_models import (
    CaseResult,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProgressEventOutbox,
)
from app.targets.base import TargetTimeoutError
from tests.concurrency.test_lease_authorization import (
    LeaseDatabase,
)
from tests.concurrency.test_lease_authorization import (
    lease_database as lease_database,
)
from tests.postgres_test_support import write_lock_diagnostic

SEEDS = tuple(range(100))
EXPECTED_FENCING = (LeaseLostError, AttemptNotActiveError, ResultAlreadyCommittedError)


@pytest.mark.integration
@pytest.mark.parametrize("seed", SEEDS)
async def test_seeded_lease_interleavings_preserve_terminal_result_and_outbox(
    lease_database: LeaseDatabase, seed: int
) -> None:
    db = lease_database
    rng = random.Random(seed)
    metrics = PlatformMetrics()
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.001, jitter_ratio=0)
    result = SQLAlchemyResultCommitter(db.factory, metrics=metrics)
    failure = SQLAlchemyFailureCommitter(db.factory, retry_policy=policy, metrics=metrics)
    heartbeat = SQLAlchemyHeartbeatService(
        db.factory, lease_duration=timedelta(seconds=30), metrics=metrics
    )
    reapers = [
        SQLAlchemyJobReaper(
            db.factory, retry_policy=policy, reaper_id=f"seed-{seed}-r{i}", metrics=metrics
        )
        for i in range(2)
    ]
    async with db.factory() as session:
        run = await session.get(EvaluationRun, db.claim.run_id)
        assert run is not None
        principal = Principal(run.tenant_id, run.created_by, "synthetic")

    trace: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        "schema_version": "evalops.random-lease-interleaving/1.0",
        "seed": seed,
        "scenario": ("live", "expired_recovery", "live_cancel", "expired_cancel")[seed % 4],
        "evalops_sha": os.getenv("EVALOPS_TEST_CODE_SHA", "UNBOUND_LOCAL_WORKTREE"),
        "trace": trace,
        "status": "FAILED",
        "model_calls": 0,
    }
    started = perf_counter()

    async def expire() -> None:
        async with db.factory.begin() as session:
            await session.execute(
                update(EvaluationJob)
                .where(
                    EvaluationJob.id == db.claim.job_id,
                    EvaluationJob.status.in_((JobStatus.RUNNING, JobStatus.CANCELLING)),
                )
                .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )

    async def commit(claim: ClaimedJob, label: str) -> None:
        await result.commit_success(
            claim=claim,
            lease_version=claim.version,
            target_result=TargetResult(
                answer=label, citations=(), sources=(), trace={}, token_usage=None, latency_ms=1
            ),
            evaluation_result=EvaluationResult(metrics={}),
        )

    async def actor(name: str, delay: float) -> None:
        await asyncio.sleep(delay)
        trace.append({"actor": name, "phase": "start", "seconds": perf_counter() - started})
        try:
            if name.startswith("success"):
                await commit(db.claim, name)
            elif name == "wrong_owner":
                await commit(
                    replace(db.claim, worker_id="synthetic-wrong-owner"), "must-not-be-accepted"
                )
                pytest.fail("wrong owner accepted")
            elif name == "heartbeat":
                await heartbeat.heartbeat(
                    job_id=db.claim.job_id,
                    worker_id=db.claim.worker_id,
                    expected_version=db.claim.version,
                )
            elif name == "failure":
                await failure.commit_failure(
                    claim=db.claim, lease_version=db.claim.version, error=TargetTimeoutError()
                )
            elif name == "cancel":
                await SQLAlchemyCancellationService(db.factory).cancel_run(
                    principal=principal, run_id=db.claim.run_id
                )
            else:
                recovered = await reapers[int(name[-1])].reap()
                trace.append({"actor": name, "recovered": len(recovered)})
        except EXPECTED_FENCING as error:
            trace.append({"actor": name, "phase": "fenced", "exception": type(error).__name__})
        else:
            trace.append({"actor": name, "phase": "completed"})

    tasks: list[asyncio.Task[None]] = []
    try:
        if seed % 2:
            await expire()
        operations = [
            "heartbeat",
            "success-a",
            "success-b",
            "failure",
            "reaper-0",
            "reaper-1",
            "wrong_owner",
        ]
        if seed % 4 >= 2:
            operations.append("cancel")
        rng.shuffle(operations)
        plan = [(name, rng.choice((0.0, 0.001, 0.003, 0.007, 0.015))) for name in operations]
        record["planned_launch_delays"] = plan
        tasks = [asyncio.create_task(actor(name, delay)) for name, delay in plan]
        async with asyncio.timeout(15):
            await asyncio.gather(*tasks)

        # Bounded recovery after the randomized race, using the real reaper/claimer.
        await expire()
        await reapers[0].reap()
        await asyncio.sleep(0.003)  # Frozen 1ms retry policy, not a lock scheduling barrier.
        claims = await SQLAlchemyJobClaimer(
            db.factory, lease_policy=LeasePolicy(timedelta(seconds=30))
        ).claim(worker_id=f"recovery-{seed}", limit=1)
        if claims:
            assert len(claims) == 1 and claims[0].job_id == db.claim.job_id
            await commit(claims[0], "recovered-current-attempt")
            trace.append({"phase": "recovery", "attempt": claims[0].attempt_number})
        with pytest.raises(EXPECTED_FENCING):
            await commit(db.claim, "late-old-result-must-not-overwrite")
        with pytest.raises(LeaseLostError):
            await heartbeat.heartbeat(
                job_id=db.claim.job_id,
                worker_id=db.claim.worker_id,
                expected_version=db.claim.version,
            )

        async with db.factory() as session:
            job = await session.get(EvaluationJob, db.claim.job_id)
            run = await session.get(EvaluationRun, db.claim.run_id)
            results = list(
                (
                    await session.scalars(
                        select(CaseResult).where(CaseResult.job_id == db.claim.job_id)
                    )
                ).all()
            )
            attempts = list(
                (
                    await session.scalars(
                        select(JobAttempt).where(JobAttempt.job_id == db.claim.job_id)
                    )
                ).all()
            )
            outbox = list(
                (
                    await session.scalars(
                        select(ProgressEventOutbox).where(
                            ProgressEventOutbox.run_id == db.claim.run_id
                        )
                    )
                ).all()
            )
            assert job is not None and run is not None
            assert job.status in (JobStatus.SUCCEEDED, JobStatus.CANCELLED, JobStatus.FAILED)
            assert run.status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED, RunStatus.FAILED)
            assert run.succeeded_jobs + run.failed_jobs + run.cancelled_jobs == run.total_jobs == 1
            assert len(results) == int(job.status is JobStatus.SUCCEEDED)
            assert len(attempts) == job.attempt_count
            assert len({a.attempt_number for a in attempts}) == len(attempts)
            assert all(a.finished_at is not None for a in attempts)
            assert job.lease_owner is None and job.lease_expires_at is None
            if results:
                accepted = next(a for a in attempts if a.id == results[0].accepted_attempt_id)
                assert accepted.outcome is AttemptOutcome.SUCCEEDED
                assert results[0].answer_json["answer"] not in {
                    "must-not-be-accepted",
                    "late-old-result-must-not-overwrite",
                }
            success_events = [
                e
                for e in outbox
                if e.event_type == "job_progress"
                and e.payload_json.get("status") == "succeeded"
                and "job_id" in e.payload_json
            ]
            assert len(success_events) == len(results)
            assert len([e for e in outbox if e.event_type == "run_completed"]) == 1
            record.update(
                status="PASSED",
                job_status=job.status.value,
                run_status=run.status.value,
                accepted_results=len(results),
                attempts=len(attempts),
                outbox_events=len(outbox),
            )
    except BaseException as error:
        record["failure_type"] = type(error).__name__
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        record["elapsed_seconds"] = perf_counter() - started
        write_lock_diagnostic(record)
