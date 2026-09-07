import asyncio
from uuid import uuid4

import httpx
import pytest

from app.domain.evaluation import EvaluationCase, ExecutionContext
from app.targets.base import TargetExecutionError
from app.targets.http_rag import HTTPRAGTarget
from tests.product_http_support import (
    FixtureResolver,
    LoopbackTargetService,
    LoopbackTargetTransport,
)


async def test_actual_socket_target_preserves_agent_fields_and_does_not_send_labels() -> None:
    context = ExecutionContext(uuid4(), uuid4(), uuid4(), 2, "socket-worker", asyncio.Event())
    async with (
        LoopbackTargetService() as service,
        httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as client,
    ):
        target = HTTPRAGTarget(
            {
                "target_id": "loopback-fixture",
                "base_url": "https://rag.example.com",
                "endpoint": "/query",
                "allowed_hosts": ["rag.example.com"],
                "include_metadata": True,
            },
            client=client,
            resolver=FixtureResolver(),
        )
        result = await target.execute_case(
            EvaluationCase(
                "case-1",
                "q",
                "hidden gold",
                {"public_context": {"locale": "zh-CN"}, "private_label": "hidden gold"},
            ),
            context,
        )
    assert result.answer == "private answer"
    assert result.trace["terminal_state"] == "completed"
    assert result.trace["tool_calls"] == []
    assert result.trace["cost_usd"] == 0.01
    assert service.requests == [
        {
            "body": {"question": "q", "metadata": {"locale": "zh-CN"}},
            "job_id": str(context.job_id),
            "attempt": "2",
        }
    ]


@pytest.mark.parametrize(
    "stall,code", [(False, "target_response_too_large"), (True, "target_timeout")]
)
async def test_real_http_response_size_and_stalled_body_are_bounded(stall: bool, code: str) -> None:
    async with (
        LoopbackTargetService(stall_body=stall) as service,
        httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as client,
    ):
        target = HTTPRAGTarget(
            {
                "target_id": "bounded-fixture",
                "base_url": "https://rag.example.com",
                "endpoint": "/query",
                "allowed_hosts": ["rag.example.com"],
                "max_response_bytes": 2 * 1024 * 1024 if stall else 64,
                "timeout_seconds": 1 if stall else 5,
            },
            client=client,
            resolver=FixtureResolver(),
        )
        with pytest.raises(TargetExecutionError) as caught:
            await target.execute_case(
                EvaluationCase("bounded", "q", None, {}),
                ExecutionContext(uuid4(), uuid4(), uuid4(), 1, "bounded-worker", asyncio.Event()),
            )
        assert caught.value.code == code
        if stall:
            assert service.body_started.is_set(), (
                "server must really send a partial body before stalling"
            )
