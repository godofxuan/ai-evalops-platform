import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.domain.evaluation import ExecutionContext
from app.jobs.claiming import ClaimedJob
from app.jobs.heartbeat import HeartbeatReceipt
from app.targets.base import TargetCancelledError
from app.workers.lease_runner import LeaseHeartbeatRunner, LeaseOperationError

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def claim() -> ClaimedJob:
    return ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={
            "case_id": "case-1",
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        },
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=NOW,
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )


class RecordingHeartbeat:
    def __init__(self, *, cancellation_requested: bool = False) -> None:
        self.cancellation_requested = cancellation_requested
        self.versions: list[int] = []

    async def heartbeat(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        expected_version: int,
    ) -> HeartbeatReceipt:
        assert job_id == JOB_ID
        assert worker_id == "worker-1"
        self.versions.append(expected_version)
        return HeartbeatReceipt(
            job_id=job_id,
            worker_id=worker_id,
            version=expected_version + 1,
            lease_expires_at=NOW,
            cancellation_requested=self.cancellation_requested,
        )


class OneHeartbeatWaiter:
    def __init__(self) -> None:
        self.calls = 0

    async def is_complete(
        self,
        task: asyncio.Task[Any],
        *,
        timeout_seconds: float,
    ) -> bool:
        assert timeout_seconds == 10
        self.calls += 1
        if self.calls == 1:
            return False
        await asyncio.sleep(0)
        return task.done()


async def test_lease_runner_returns_latest_fencing_version() -> None:
    heartbeat = RecordingHeartbeat()
    runner = LeaseHeartbeatRunner(
        heartbeat_service=heartbeat,
        heartbeat_interval_seconds=10,
        waiter=OneHeartbeatWaiter(),
    )
    execution_context = ExecutionContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        cancellation=asyncio.Event(),
    )

    result, version = await runner.run(
        claim=claim(),
        context=execution_context,
        operation=_completed_operation(),
    )

    assert result == "done"
    assert version == 3
    assert heartbeat.versions == [2]


async def test_lease_runner_cancels_operation_when_database_requests_cancel() -> None:
    runner = LeaseHeartbeatRunner(
        heartbeat_service=RecordingHeartbeat(cancellation_requested=True),
        heartbeat_interval_seconds=10,
        waiter=OneHeartbeatWaiter(),
    )
    execution_context = ExecutionContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        cancellation=asyncio.Event(),
    )

    with pytest.raises(LeaseOperationError) as captured:
        await runner.run(
            claim=claim(),
            context=execution_context,
            operation=_never_finishes(),
        )
    assert execution_context.cancellation.is_set()
    assert isinstance(captured.value.error, TargetCancelledError)
    assert captured.value.lease_version == 3


async def _completed_operation() -> str:
    return "done"


async def _never_finishes() -> str:
    await asyncio.Event().wait()
    return "unreachable"
