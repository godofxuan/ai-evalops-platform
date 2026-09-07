import asyncio
import base64
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.export_service import encode_report
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs  # noqa: F401


@pytest.mark.asyncio
async def test_redirect_never_forwards_credentials_or_exposes_response_body() -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example/"}, text="secret")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream), follow_redirects=True) as http,
        ProductAPIClient("https://eval.example", "private-key", http=http) as client,
    ):
        with pytest.raises(ProductAPIError, match="^api_http_307$"):
            await client.get(uuid4())
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer private-key"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/?token=x",
        "https://example.com/path",
    ],
)
def test_unsafe_api_base_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="invalid_api_url"):
        ProductAPIClient(url, "private-key")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,suffix",
    [("get", "GET", ""), ("cancel", "POST", "/cancel"), ("wait", "GET", "")],
)
async def test_recover_and_cancel_use_the_original_experiment_id(
    operation: str, method: str, suffix: str
) -> None:
    experiment_id = uuid4()
    run = {
        "id": str(uuid4()),
        "dataset_version_id": str(uuid4()),
        "status": "queued",
        "total_jobs": 2,
        "succeeded_jobs": 0,
        "failed_jobs": 0,
        "cancelled_jobs": 0,
        "created_at": "2026-09-07T00:00:00Z",
        "started_at": None,
        "finished_at": None,
    }
    body = {
        "id": str(experiment_id),
        "state": "QUEUED",
        "cancel_requested": False,
        "baseline": run,
        "candidate": {**run, "id": str(uuid4())},
    }

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.method == method
        assert request.url.path == f"/api/v1/experiments/{experiment_id}{suffix}"
        if operation == "wait":
            body["state"] = "EXECUTION_FAILED"
        return httpx.Response(202 if operation == "cancel" else 200, content=json.dumps(body))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http,
        ProductAPIClient("http://127.0.0.1:8000", "key", http=http) as client,
    ):
        if operation == "get":
            result = await client.get(experiment_id)
        elif operation == "cancel":
            result = await client.cancel(experiment_id)
        else:
            result = await client.wait(experiment_id, wait_seconds=1)
    assert result.id == experiment_id
    assert result.state == ("EXECUTION_FAILED" if operation == "wait" else "QUEUED")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,limit,error",
    [(b'{"id":1,"id":2}', 100, "api_response_invalid"), (b"x" * 101, 100, "api_response_limit")],
)
async def test_bad_or_oversized_responses_are_safe_errors(
    body: bytes, limit: int, error: str
) -> None:
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        ) as http,
        ProductAPIClient(
            "https://eval.example", "key", http=http, max_response_bytes=limit
        ) as client,
    ):
        with pytest.raises(ProductAPIError, match=f"^{error}$"):
            await client.get(uuid4())


@pytest.mark.asyncio
async def test_wait_timeout_does_not_cancel_the_server_experiment() -> None:
    methods: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        await asyncio.sleep(5)
        return httpx.Response(200)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http,
        ProductAPIClient("https://eval.example", "key", http=http) as client,
    ):
        with pytest.raises(ProductAPIError, match="^api_wait_timeout$"):
            await client.wait(uuid4(), wait_seconds=0.01)
    assert methods == ["GET"]


@pytest.mark.asyncio
async def test_submission_preserves_original_bytes_and_idempotency_key(
    submission_inputs: dict[str, Any],  # noqa: F811
) -> None:
    experiment_id = uuid4()
    reply = {
        "id": str(experiment_id),
        "baseline_run_id": str(uuid4()),
        "candidate_run_id": str(uuid4()),
        "status_url": f"/api/v1/experiments/{experiment_id}",
    }

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/experiments"
        assert request.headers["Idempotency-Key"] == "stable-pair"
        body = json.loads(request.content)
        assert base64.b64decode(body["dataset_base64"]) == submission_inputs["dataset_payload"]
        assert body["request"] == submission_inputs["request"].model_dump(mode="json")
        return httpx.Response(202, json=reply)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http,
        ProductAPIClient("https://eval.example", "key", http=http) as client,
    ):
        for _ in range(2):
            accepted = await client.submit(
                request=submission_inputs["request"],
                dataset_payload=submission_inputs["dataset_payload"],
                idempotency_key="stable-pair",
            )
            assert accepted.id == experiment_id


@pytest.mark.asyncio
async def test_private_export_requires_explicit_opt_in_and_preserves_bytes(durable_evidence):
    from uuid import UUID

    snapshot, raw = durable_evidence
    payload = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    experiment_id = UUID(snapshot["experiment_id"])

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/experiments/{experiment_id}/export"
        return httpx.Response(200, content=payload)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http,
        ProductAPIClient("https://eval.example", "key", http=http) as client,
    ):
        assert await client.export(experiment_id, include_private=True) == payload
        with pytest.raises(ProductAPIError, match="^api_export_visibility$"):
            await client.export(experiment_id)
