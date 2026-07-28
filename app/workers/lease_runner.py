import asyncio
from collections.abc import Coroutine
from contextlib import suppress
from typing import Any, Protocol, TypeVar

from app.domain.evaluation import ExecutionContext
from app.jobs.claiming import ClaimedJob
from app.jobs.heartbeat import HeartbeatReceipt
from app.targets.base import TargetCancelledError

T = TypeVar("T")


class LeaseOperationError(RuntimeError):
    def __init__(self, error: BaseException, *, lease_version: int) -> None:
        super().__init__("leased operation failed")
        self.error = error
        self.lease_version = lease_version


class HeartbeatService(Protocol):
    async def heartbeat(
        self,
        *,
        job_id: Any,
        worker_id: str,
        expected_version: int,
    ) -> HeartbeatReceipt:
        """Extend an owned lease and return the next fencing version."""


class CompletionWaiter(Protocol):
    async def is_complete(
        self,
        task: asyncio.Task[Any],
        *,
        timeout_seconds: float,
    ) -> bool:
        """Wait until completion or the next heartbeat tick."""


class AsyncIOCompletionWaiter:
    async def is_complete(
        self,
        task: asyncio.Task[Any],
        *,
        timeout_seconds: float,
    ) -> bool:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
        return task in done


class LeaseHeartbeatRunner:
    def __init__(
        self,
        *,
        heartbeat_service: HeartbeatService,
        heartbeat_interval_seconds: float,
        waiter: CompletionWaiter | None = None,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._heartbeat_service = heartbeat_service
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._waiter = waiter or AsyncIOCompletionWaiter()

    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: Coroutine[Any, Any, T],
    ) -> tuple[T, int]:
        task = asyncio.create_task(operation)
        version = claim.version
        try:
            while not await self._waiter.is_complete(
                task,
                timeout_seconds=self._heartbeat_interval_seconds,
            ):
                receipt = await self._heartbeat_service.heartbeat(
                    job_id=claim.job_id,
                    worker_id=claim.worker_id,
                    expected_version=version,
                )
                version = receipt.version
                if receipt.cancellation_requested:
                    context.cancellation.set()
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise LeaseOperationError(
                        TargetCancelledError(),
                        lease_version=version,
                    )
            try:
                return await task, version
            except Exception as error:
                raise LeaseOperationError(error, lease_version=version) from error
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
