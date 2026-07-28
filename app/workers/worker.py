import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Protocol, TypeVar

from app.domain.evaluation import (
    EvaluationCase,
    EvaluationResult,
    ExecutionContext,
    TargetResult,
)
from app.evaluators.base import Evaluator, build_evaluator
from app.jobs.claiming import ClaimedJob
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
    ) -> object:
        """Persist an owned successful result."""


class FailureCommitter(Protocol):
    async def commit_failure(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        error: BaseException,
    ) -> object:
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
    ) -> None:
        self._claimer = claimer
        self._result_committer = result_committer
        self._failure_committer = failure_committer
        self._lease_runner = lease_runner
        self._target_factory = target_factory
        self._evaluator_factory = evaluator_factory

    async def process_one(self, *, worker_id: str) -> bool:
        claims = await self._claimer.claim(worker_id=worker_id, limit=1)
        if not claims:
            return False
        claim = claims[0]
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
        try:
            target = self._target_factory(claim.target_type, claim.target_config)
            evaluator = self._evaluator_factory(
                claim.evaluator_type,
                claim.evaluator_config,
            )
            timeout_seconds = _case_timeout_seconds(claim.evaluator_config)
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
            evaluation_result = evaluator.evaluate(
                case,
                target_result,
                attempt_number=claim.attempt_number,
            )
        except LeaseOperationError as error:
            await self._failure_committer.commit_failure(
                claim=claim,
                lease_version=error.lease_version,
                error=error.error,
            )
            return True
        except Exception as error:
            await self._failure_committer.commit_failure(
                claim=claim,
                lease_version=lease_version,
                error=error,
            )
            return True
        await self._result_committer.commit_success(
            claim=claim,
            lease_version=claim.version,
            target_result=target_result,
            evaluation_result=evaluation_result,
        )
        return True


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
