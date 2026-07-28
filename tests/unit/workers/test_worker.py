from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from app.domain.evaluation import (
    EvaluationCase,
    EvaluationResult,
    ExecutionContext,
    TargetResult,
    TokenUsage,
)
from app.jobs.claiming import ClaimedJob
from app.targets.base import TargetHTTPError
from app.workers.worker import EvaluationWorker

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class SingleClaimer:
    def __init__(self, claim: ClaimedJob) -> None:
        self.claimed_job = claim

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        assert worker_id == "worker-1"
        assert limit == 1
        return (self.claimed_job,)


class RecordingTarget:
    def __init__(self) -> None:
        self.case_id: str | None = None

    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        self.case_id = case.case_id
        assert context.attempt_number == 1
        return TargetResult(
            answer="4",
            citations=(),
            sources=(),
            trace={},
            token_usage=TokenUsage(input_tokens=5, output_tokens=1),
            latency_ms=12,
        )


class RecordingEvaluator:
    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        assert case.case_id == "case-1"
        assert target_result.answer == "4"
        assert attempt_number == 1
        return EvaluationResult(metrics={"lexical_exact_match": True})


class RecordingCommitter:
    def __init__(self) -> None:
        self.committed = False

    async def commit_success(self, **kwargs: object) -> None:
        self.committed = True
        assert kwargs["lease_version"] == 2
        assert cast(TargetResult, kwargs["target_result"]).answer == "4"


class RecordingFailureCommitter:
    def __init__(self) -> None:
        self.failure: BaseException | None = None

    async def commit_failure(self, **kwargs: object) -> None:
        self.failure = cast(BaseException, kwargs["error"])


class PassThroughLeaseRunner:
    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: object,
    ) -> tuple[TargetResult, int]:
        del context
        return await cast(Any, operation), claim.version


async def test_worker_executes_target_evaluator_and_result_commit_pipeline() -> None:
    claim = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={
            "case_id": "case-1",
            "question": "What is 2 + 2?",
            "expected_answer": "4",
            "metadata": {},
        },
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="basic_answer",
        evaluator_config={},
        evaluator_version="v1",
    )
    target = RecordingTarget()
    evaluator = RecordingEvaluator()
    committer = RecordingCommitter()
    failure_committer = RecordingFailureCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claim),
        target_factory=lambda _kind, _config: target,
        evaluator_factory=lambda _kind, _config: evaluator,
        result_committer=committer,
        failure_committer=failure_committer,
        lease_runner=PassThroughLeaseRunner(),
    )

    processed = await worker.process_one(worker_id="worker-1")

    assert processed is True
    assert target.case_id == "case-1"
    assert committer.committed is True
    assert failure_committer.failure is None


class FailingTarget(RecordingTarget):
    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        del case, context
        raise TargetHTTPError(429)


async def test_worker_persists_target_failure_instead_of_losing_claim() -> None:
    claimed_job = ClaimedJob(
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
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )
    result_committer = RecordingCommitter()
    failure_committer = RecordingFailureCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: FailingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=result_committer,
        failure_committer=failure_committer,
        lease_runner=PassThroughLeaseRunner(),
    )

    assert await worker.process_one(worker_id="worker-1") is True
    assert isinstance(failure_committer.failure, TargetHTTPError)
    assert result_committer.committed is False
