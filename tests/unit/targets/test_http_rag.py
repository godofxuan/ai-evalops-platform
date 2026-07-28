import asyncio
import json
from uuid import UUID

import httpx
import pytest

from app.domain.evaluation import EvaluationCase, ExecutionContext
from app.targets.base import InvalidTargetConfiguration
from app.targets.http_rag import HTTPRAGTarget

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class StaticResolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == "rag.example.com"
        return self.addresses


def context() -> ExecutionContext:
    return ExecutionContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        cancellation=asyncio.Event(),
    )


@pytest.mark.parametrize(
    "config",
    [
        {
            "base_url": "http://rag.example.com",
            "endpoint": "/query",
            "allowed_hosts": ["rag.example.com"],
        },
        {
            "base_url": "https://localhost",
            "endpoint": "/query",
            "allowed_hosts": ["localhost"],
        },
        {
            "base_url": "https://rag.example.com",
            "endpoint": "https://evil.example/query",
            "allowed_hosts": ["rag.example.com"],
        },
        {
            "base_url": "https://rag.example.com",
            "endpoint": "/query",
            "allowed_hosts": ["rag.example.com"],
            "authentication": {"bearer": "plaintext-secret"},
        },
    ],
)
def test_http_target_rejects_unsafe_url_configuration(config: dict[str, object]) -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(config)


async def test_http_target_resolves_public_ip_maps_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_TEST_TOKEN", "secret-value")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://rag.example.com/v1/query")
        assert request.headers["Authorization"] == "Bearer secret-value"
        assert request.headers["X-EvalOps-Job-ID"] == str(JOB_ID)
        assert json.loads(request.content) == {"prompt": "What is 2 + 2?"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "answer": "4",
                    "citations": [{"source_id": "math"}],
                    "sources": [{"id": "math", "visible": True}],
                    "trace": {"request_id": "upstream-1"},
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            {
                "base_url": "https://rag.example.com",
                "endpoint": "/v1/query",
                "allowed_hosts": ["rag.example.com"],
                "auth_env_var": "RAG_TEST_TOKEN",
                "request_question_field": "prompt",
                "answer_path": "data.answer",
                "citations_path": "data.citations",
                "sources_path": "data.sources",
                "trace_path": "data.trace",
                "usage_path": "data.usage",
            },
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )
        result = await target.execute_case(
            EvaluationCase(
                case_id="case-1",
                question="What is 2 + 2?",
                expected_answer="4",
                metadata={},
            ),
            context(),
        )

    assert result.answer == "4"
    assert result.citations == ({"source_id": "math"},)
    assert result.token_usage is not None
    assert result.token_usage.output_tokens == 1


async def test_http_target_rejects_private_dns_resolution() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        target = HTTPRAGTarget(
            {
                "base_url": "https://rag.example.com",
                "endpoint": "/query",
                "allowed_hosts": ["rag.example.com"],
            },
            client=client,
            resolver=StaticResolver("127.0.0.1"),
        )
        with pytest.raises(InvalidTargetConfiguration, match="public"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-private",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )
