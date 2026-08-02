from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.telemetry import Telemetry
from app.domain.evaluation import (
    EvaluationCase,
    EvaluationResult,
    ExecutionContext,
    TargetResult,
    TokenUsage,
)
from app.events.models import ProgressEvent
from app.jobs.claiming import ClaimedJob
from app.observability.metrics import PlatformMetrics
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


class RenewingLeaseRunner(PassThroughLeaseRunner):
    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: object,
    ) -> tuple[TargetResult, int]:
        del context
        return await cast(Any, operation), claim.version + 3


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
    metrics = PlatformMetrics()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: FailingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=result_committer,
        failure_committer=failure_committer,
        lease_runner=PassThroughLeaseRunner(),
        metrics=metrics,
    )

    assert await worker.process_one(worker_id="worker-1") is True
    assert isinstance(failure_committer.failure, TargetHTTPError)
    assert result_committer.committed is False
    assert (
        'db_operation_duration_seconds_count{operation="failure"} 1.0'
        in metrics.render().decode("utf-8")
    )


async def test_worker_commits_with_latest_heartbeat_lease_version() -> None:
    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
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

    class LatestVersionCommitter:
        async def commit_success(self, **kwargs: object) -> None:
            assert kwargs["lease_version"] == 5

    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=LatestVersionCommitter(),
        failure_committer=RecordingFailureCommitter(),
        lease_runner=RenewingLeaseRunner(),
    )

    assert await worker.process_one(worker_id="worker-1") is True


async def test_worker_never_publishes_outside_the_state_transaction() -> None:
    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
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

    class ForbiddenPublisher:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(self, event: ProgressEvent) -> bool:
            del event
            self.calls += 1
            return True

    committer = RecordingCommitter()
    publisher = ForbiddenPublisher()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=committer,
        failure_committer=RecordingFailureCommitter(),
        lease_runner=PassThroughLeaseRunner(),
        event_publisher=publisher,
    )

    assert await worker.process_one(worker_id="worker-1") is True
    assert committer.committed is True
    assert publisher.calls == 0


async def test_worker_emits_pipeline_spans_and_success_metrics() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-worker-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )
    with telemetry.start_as_current_span("run.create") as origin_span:
        origin_context = origin_span.get_span_context()
        origin_traceparent = telemetry.capture_traceparent()
    assert origin_traceparent is not None

    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
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
        origin_traceparent=origin_traceparent,
    )
    metrics = PlatformMetrics()

    class ForbiddenPublisher:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(self, event: ProgressEvent) -> bool:
            del event
            self.calls += 1
            return True

    publisher = ForbiddenPublisher()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=RecordingCommitter(),
        failure_committer=RecordingFailureCommitter(),
        lease_runner=PassThroughLeaseRunner(),
        event_publisher=publisher,
        metrics=metrics,
        telemetry=telemetry,
    )

    assert await worker.process_one(worker_id="worker-1") is True

    spans = exporter.get_finished_spans()
    span_names = {span.name for span in spans}
    assert {
        "job.claim",
        "job.process",
        "target.call",
        "evaluator.evaluate",
        "result.persist",
    } <= span_names
    assert "progress.publish" not in span_names
    assert publisher.calls == 0
    process_span = next(span for span in spans if span.name == "job.process")
    assert process_span.parent is None
    assert process_span.context.trace_id != origin_context.trace_id
    assert len(process_span.links) == 1
    assert process_span.links[0].context.trace_id == origin_context.trace_id
    assert process_span.links[0].context.span_id == origin_context.span_id
    assert process_span.attributes is not None
    assert process_span.attributes["attempt.number"] == 1
    rendered = metrics.render().decode("utf-8")
    assert "job_succeeded_total 1.0" in rendered
    assert "case_duration_count 1.0" in rendered
    assert 'db_operation_duration_seconds_count{operation="claim"} 1.0' in rendered
    assert 'db_operation_duration_seconds_count{operation="result"} 1.0' in rendered
