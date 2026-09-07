import asyncio
from uuid import uuid4

import httpx

from app.domain.evaluation import EvaluationCase, ExecutionContext
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
