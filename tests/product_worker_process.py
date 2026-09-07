"""An actual spawned worker; barriers inject death without faking database or target results."""

import asyncio
import os
from collections.abc import Mapping
from datetime import timedelta
from multiprocessing.connection import Connection
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.evaluation import EvaluationCase, ExecutionContext, TargetResult
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import create_session_factory
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from tests.product_http_support import FixtureResolver, LoopbackTargetTransport


def run_crash_worker(database_url: str, port: int, phase: str, barrier: Connection) -> None:
    if os.environ.get("EVALOPS_RUN_INTEGRATION") != "1" or phase not in {"claimed", "after_http"}:
        raise RuntimeError("isolated integration environment required")
    try:
        asyncio.run(_run(database_url, port, phase, barrier))
    except Exception as error:
        barrier.send(("worker_error", type(error).__name__))
    finally:
        barrier.close()


async def _run(database_url: str, port: int, phase: str, barrier: Connection) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = create_session_factory(engine)
    captured: list[ClaimedJob] = []
    lease = timedelta(seconds=1)

    async def pause(claim: ClaimedJob) -> None:
        barrier.send(claim)
        await asyncio.Event().wait()  # Parent kills this exact process after receiving the barrier.

    class BarrierClaimer(SQLAlchemyJobClaimer):
        async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
            claims = await super().claim(worker_id=worker_id, limit=limit)
            captured.extend(claims)
            if claims and phase == "claimed":
                await pause(claims[0])
            return claims

    try:
        async with httpx.AsyncClient(transport=LoopbackTargetTransport(port)) as client:

            class BarrierTarget:
                def __init__(self, config: Mapping[str, Any]) -> None:
                    self.inner = HTTPRAGTarget(config, client=client, resolver=FixtureResolver())

                async def execute_case(
                    self, case: EvaluationCase, context: ExecutionContext
                ) -> TargetResult:
                    result = await self.inner.execute_case(case, context)
                    if phase == "after_http":
                        await pause(captured[0])
                    return result

            def target_factory(kind: str, config: Mapping[str, Any]) -> BarrierTarget:
                assert kind == "http_rag"
                return BarrierTarget(config)

            worker = EvaluationWorker(
                claimer=BarrierClaimer(factory, lease_policy=LeasePolicy(lease)),
                result_committer=SQLAlchemyResultCommitter(factory),
                failure_committer=SQLAlchemyFailureCommitter(factory, retry_policy=RetryPolicy()),
                lease_runner=LeaseHeartbeatRunner(
                    heartbeat_service=SQLAlchemyHeartbeatService(factory, lease_duration=lease),
                    heartbeat_interval_seconds=0.2,
                ),
                target_factory=target_factory,
            )
            completed = await worker.process_one(worker_id=f"crash-fixture-{phase}")
            barrier.send(("unexpected_completion", completed))
    finally:
        await engine.dispose()
