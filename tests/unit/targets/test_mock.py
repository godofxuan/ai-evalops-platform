import asyncio
from uuid import UUID

import pytest

from app.domain.evaluation import EvaluationCase, ExecutionContext
from app.targets.base import TargetCancelledError, TargetHTTPError
from app.targets.mock import MockTarget

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay_seconds: float) -> None:
        self.delays.append(delay_seconds)


def context(attempt_number: int = 1) -> ExecutionContext:
    return ExecutionContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=attempt_number,
        worker_id="worker-1",
        cancellation=asyncio.Event(),
    )


async def test_mock_target_returns_deterministic_answer_sources_and_usage() -> None:
    sleeper = RecordingSleeper()
    target = MockTarget(
        {
            "fixed_delay_ms": 25,
            "answer": "fixed answer",
            "sources": [{"id": "source-1", "visible": True}],
            "citations": [{"source_id": "source-1"}],
            "input_tokens": 12,
            "output_tokens": 4,
        },
        sleeper=sleeper,
    )

    result = await target.execute_case(
        EvaluationCase(
            case_id="case-1",
            question="q",
            expected_answer="a",
            metadata={},
        ),
        context(),
    )

    assert result.answer == "fixed answer"
    assert result.sources == ({"id": "source-1", "visible": True},)
    assert result.token_usage is not None
    assert result.token_usage.input_tokens == 12
    assert result.latency_ms == 25
    assert sleeper.delays == [0.025]


async def test_mock_target_fails_until_configured_attempt_then_succeeds() -> None:
    target = MockTarget({"answer": "eventual", "fail_until_attempt": 2})
    case = EvaluationCase(
        case_id="case-retry",
        question="q",
        expected_answer="a",
        metadata={},
    )

    for attempt in (1, 2):
        with pytest.raises(TargetHTTPError) as captured:
            await target.execute_case(case, context(attempt))
        assert captured.value.status_code == 503
    assert (await target.execute_case(case, context(3))).answer == "eventual"


async def test_mock_target_observes_preexisting_cancellation() -> None:
    execution_context = context()
    execution_context.cancellation.set()

    with pytest.raises(TargetCancelledError):
        await MockTarget({}).execute_case(
            EvaluationCase(
                case_id="case-cancelled",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            execution_context,
        )
