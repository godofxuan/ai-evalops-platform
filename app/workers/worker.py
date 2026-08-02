import asyncio
from collections.abc import Callable, Coroutine, Mapping
from contextlib import AbstractContextManager, nullcontext
from time import perf_counter
from typing import Any, Protocol, TypeVar, cast

import structlog

from app.core.telemetry import Telemetry
from app.domain.evaluation import (
    EvaluationCase,
    EvaluationResult,
    ExecutionContext,
    TargetResult,
)
from app.evaluators.base import Evaluator, build_evaluator
from app.jobs.claiming import ClaimedJob
from app.jobs.failures import FailureCommitReceipt
from app.jobs.results import ResultCommitReceipt
from app.observability.metrics import PlatformMetrics
from app.targets.base import EvaluationTarget, TargetTimeoutError, build_target
from app.workers.lease_runner import LeaseOperationError

type TargetFactory = Callable[[str, Mapping[str, Any]], EvaluationTarget]
type EvaluatorFactory = Callable[[str, Mapping[str, Any]], Evaluator]
T = TypeVar("T")


class JobClaimer(Protocol):
    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        """Return committed claims."""


class ResultCommitter(Protocol):
    async def commit_success(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        target_result: TargetResult,
        evaluation_result: EvaluationResult,
    ) -> ResultCommitReceipt:
        """Persist an owned successful result."""


class FailureCommitter(Protocol):
    async def commit_failure(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        error: BaseException,
    ) -> FailureCommitReceipt:
        """Persist a retry, permanent failure, or cooperative cancellation."""


class LeaseRunner(Protocol):
    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: Coroutine[Any, Any, T],
    ) -> tuple[T, int]:
        """Run an operation while maintaining its lease."""


class InvalidCaseTimeout(ValueError):
    """The evaluator configuration has an unsafe per-case timeout."""


class EvaluationWorker:
    def __init__(
        self,
        *,
        claimer: JobClaimer,
        result_committer: ResultCommitter,
        failure_committer: FailureCommitter,
        lease_runner: LeaseRunner,
        target_factory: TargetFactory = build_target,
        evaluator_factory: EvaluatorFactory = build_evaluator,
        metrics: PlatformMetrics | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._claimer = claimer
        self._result_committer = result_committer
        self._failure_committer = failure_committer
        self._lease_runner = lease_runner
        self._target_factory = target_factory
        self._evaluator_factory = evaluator_factory
        self._metrics = metrics
        self._telemetry = telemetry

    async def process_one(self, *, worker_id: str) -> bool:
        claim_started_at = perf_counter()
        try:
            with self._span("job.claim", {"worker.id": worker_id}):
                claims = await self._claimer.claim(worker_id=worker_id, limit=1)
        finally:
            if self._metrics is not None:
                self._metrics.observe_db_operation(
                    operation="claim",
                    duration_seconds=perf_counter() - claim_started_at,
                )
        if not claims:
            return False
        claim = claims[0]
        with self._span(
            "job.process",
            {
                "tenant.id": str(claim.tenant_id),
                "run.id": str(claim.run_id),
                "job.id": str(claim.job_id),
                "attempt.id": str(claim.attempt_id),
                "attempt.number": claim.attempt_number,
                "worker.id": worker_id,
            },
            origin_traceparent=claim.origin_traceparent,
        ):
            trace_id = None if self._telemetry is None else self._telemetry.current_trace_id()
            log_context = {
                "tenant_id": str(claim.tenant_id),
                "run_id": str(claim.run_id),
                "job_id": str(claim.job_id),
                "attempt_id": str(claim.attempt_id),
                "worker_id": worker_id,
            }
            if trace_id is not None:
                log_context["trace_id"] = trace_id
            with structlog.contextvars.bound_contextvars(**log_context):
                return await self._process_claim(claim)

    async def _process_claim(self, claim: ClaimedJob) -> bool:
        case = EvaluationCase.from_payload(claim.case_payload)
        context = ExecutionContext(
            run_id=claim.run_id,
            job_id=claim.job_id,
            attempt_id=claim.attempt_id,
            attempt_number=claim.attempt_number,
            worker_id=claim.worker_id,
            cancellation=asyncio.Event(),
        )
        lease_version = claim.version
        case_started_at = perf_counter()
        try:
            target = self._target_factory(claim.target_type, claim.target_config)
            evaluator = self._evaluator_factory(
                claim.evaluator_type,
                claim.evaluator_config,
            )
            timeout_seconds = _case_timeout_seconds(claim.evaluator_config)
            with self._span("target.call"):
                target_result, lease_version = await self._lease_runner.run(
                    claim=claim,
                    context=context,
                    operation=_execute_with_timeout(
                        target=target,
                        case=case,
                        context=context,
                        timeout_seconds=timeout_seconds,
                    ),
                )
            with self._span("evaluator.evaluate"):
                evaluation_result = evaluator.evaluate(
                    case,
                    target_result,
                    attempt_number=claim.attempt_number,
                )
        except LeaseOperationError as error:
            failure_receipt = await self._commit_failure(
                claim=claim,
                lease_version=error.lease_version,
                error=error.error,
            )
            self._record_failure_metric(failure_receipt)
            return True
        except Exception as error:
            failure_receipt = await self._commit_failure(
                claim=claim,
                lease_version=lease_version,
                error=error,
            )
            self._record_failure_metric(failure_receipt)
            return True
        finally:
            if self._metrics is not None:
                self._metrics.observe_case_duration(perf_counter() - case_started_at)
        result_started_at = perf_counter()
        try:
            with self._span("result.persist"):
                await self._result_committer.commit_success(
                    claim=claim,
                    lease_version=lease_version,
                    target_result=target_result,
                    evaluation_result=evaluation_result,
                )
        finally:
            if self._metrics is not None:
                self._metrics.observe_db_operation(
                    operation="result",
                    duration_seconds=perf_counter() - result_started_at,
                )
        if self._metrics is not None:
            self._metrics.record_job_succeeded()
        return True

    async def _commit_failure(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        error: BaseException,
    ) -> FailureCommitReceipt:
        started_at = perf_counter()
        try:
            with self._span("failure.persist"):
                return await self._failure_committer.commit_failure(
                    claim=claim,
                    lease_version=lease_version,
                    error=error,
                )
        finally:
            if self._metrics is not None:
                self._metrics.observe_db_operation(
                    operation="failure",
                    duration_seconds=perf_counter() - started_at,
                )

    def _record_failure_metric(self, receipt: object) -> None:
        if self._metrics is None:
            return
        if getattr(receipt, "retryable", False):
            self._metrics.record_job_retry()
        elif getattr(getattr(receipt, "status", None), "value", None) == "failed":
            self._metrics.record_job_failed()

    def _span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        origin_traceparent: str | None = None,
    ) -> AbstractContextManager[object]:
        if self._telemetry is None:
            return nullcontext()
        return cast(
            AbstractContextManager[object],
            self._telemetry.start_as_current_span(
                name,
                attributes=attributes,
                links=self._telemetry.links_from_traceparent(origin_traceparent),
            ),
        )


async def _execute_with_timeout(
    *,
    target: EvaluationTarget,
    case: EvaluationCase,
    context: ExecutionContext,
    timeout_seconds: float,
) -> TargetResult:
    try:
        async with asyncio.timeout(timeout_seconds):
            return await target.execute_case(case, context)
    except TimeoutError:
        raise TargetTimeoutError from None


def _case_timeout_seconds(config: Mapping[str, Any]) -> float:
    value = config.get("case_timeout_seconds", 30.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 300:
        raise InvalidCaseTimeout("case_timeout_seconds must be within (0, 300]")
    return float(value)
